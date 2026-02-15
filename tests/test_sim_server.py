from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from doaj_reviewer.sim_server import (
    SimulationApp,
    build_raw_submission_from_form,
    split_urls,
    validate_raw_submission,
)


RULESET_PATH = Path(__file__).resolve().parents[1] / "specs" / "reviewer" / "rules" / "ruleset.must.v1.json"


class SimServerHelperTests(unittest.TestCase):
    def test_split_urls_supports_newline_and_pipe(self) -> None:
        raw = "https://a.example|https://b.example\nhttps://a.example\n\nhttps://c.example"
        self.assertEqual(
            split_urls(raw),
            ["https://a.example", "https://b.example", "https://c.example"],
        )

    def test_build_raw_submission_from_form(self) -> None:
        payload = {
            "submission_id": "SIM-10",
            "journal_homepage_url": "https://journal.example",
            "publication_model": "issue_based",
            "editorial_board": "https://journal.example/editorial-board",
            "latest_content": "https://journal.example/issue-2\nhttps://journal.example/issue-1",
            "open_access_statement": "https://journal.example/open-access",
        }
        raw = build_raw_submission_from_form(payload)
        self.assertEqual(raw["submission_id"], "SIM-10")
        self.assertEqual(raw["journal_homepage_url"], "https://journal.example")
        self.assertEqual(raw["publication_model"], "issue_based")
        self.assertEqual(raw["source_urls"]["latest_content"][0], "https://journal.example/issue-2")

    def test_validate_raw_submission(self) -> None:
        valid = {
            "submission_id": "S1",
            "journal_homepage_url": "https://journal.example",
            "publication_model": "issue_based",
            "source_urls": {
                "editorial_board": ["https://journal.example/editorial-board"],
                "latest_content": ["https://journal.example/issue-1"],
            },
        }
        invalid = {
            "submission_id": "S2",
            "journal_homepage_url": "",
            "publication_model": "issue_based",
            "source_urls": {},
        }
        self.assertEqual(validate_raw_submission(valid), [])
        self.assertTrue(validate_raw_submission(invalid))

    def test_export_csv_aggregates_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"

            run_old = runs_dir / "20260215-aaa11111"
            run_old.mkdir(parents=True, exist_ok=True)
            (run_old / "submission.raw.json").write_text(
                json.dumps(
                    {
                        "submission_id": "SIM-OLD",
                        "journal_homepage_url": "https://journal.example",
                    }
                ),
                encoding="utf-8",
            )
            (run_old / "review-summary.json").write_text(
                json.dumps(
                    {
                        "submission_id": "SIM-OLD",
                        "overall_result": "pass",
                        "checks": [
                            {"rule_id": "doaj.open_access_statement.v1", "result": "pass"},
                            {"rule_id": "doaj.endogeny.v1", "result": "need_human_review"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            run_new = runs_dir / "20260216-bbb22222"
            run_new.mkdir(parents=True, exist_ok=True)
            (run_new / "submission.raw.json").write_text(
                json.dumps(
                    {
                        "submission_id": "SIM-NEW",
                        "journal_homepage_url": "https://journal.example",
                    }
                ),
                encoding="utf-8",
            )

            app = SimulationApp(ruleset_path=RULESET_PATH, runs_dir=runs_dir)
            content = app.render_export_csv(limit=None)
            rows = list(csv.DictReader(io.StringIO(content)))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["run_id"], "20260216-bbb22222")
            self.assertEqual(rows[0]["submission_id"], "SIM-NEW")
            self.assertEqual(rows[0]["overall_result"], "not_available")
            self.assertEqual(rows[1]["run_id"], "20260215-aaa11111")
            self.assertEqual(rows[1]["submission_id"], "SIM-OLD")
            self.assertEqual(rows[1]["overall_result"], "pass")
            self.assertEqual(rows[1]["doaj.open_access_statement.v1"], "pass")
            self.assertEqual(rows[1]["doaj.endogeny.v1"], "need_human_review")


if __name__ == "__main__":
    unittest.main()
