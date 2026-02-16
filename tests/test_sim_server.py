from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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

    def test_build_raw_submission_with_manual_text_and_invalid_pdf(self) -> None:
        payload = {
            "submission_id": "SIM-MANUAL",
            "journal_homepage_url": "https://journal.example",
            "publication_model": "issue_based",
            "open_access_statement": "https://journal.example/open-access",
            "issn_consistency": "https://journal.example/about",
            "publisher_identity": "https://journal.example/publisher",
            "license_terms": "https://journal.example/licensing",
            "copyright_author_rights": "https://journal.example/copyright",
            "peer_review_policy": "https://journal.example/peer-review",
            "aims_scope": "https://journal.example/aims-scope",
            "editorial_board": "https://journal.example/editorial-board",
            "latest_content": "https://journal.example/issue-1",
            "instructions_for_authors": "https://journal.example/instructions",
            "publication_fees_disclosure": "https://journal.example/apc",
            "manual_policy_pages": [
                {
                    "rule_hint": "open_access_statement",
                    "title": "Manual fallback text",
                    "source_label": "manual://open_access_statement/text",
                    "text": "This journal provides open access under CC BY terms.",
                },
                {
                    "rule_hint": "peer_review_policy",
                    "title": "Manual PDF",
                    "source_label": "manual://peer_review_policy/pdf",
                    "file_name": "peer-review.pdf",
                    "pdf_base64": "this-is-not-base64",
                },
            ],
        }
        raw = build_raw_submission_from_form(payload)
        self.assertIn("manual_policy_pages", raw)
        self.assertEqual(len(raw["manual_policy_pages"]), 1)
        self.assertEqual(raw["manual_policy_pages"][0]["rule_hint"], "open_access_statement")
        self.assertIn("manual_input_warnings", raw)
        self.assertTrue(any("could not be decoded" in item for item in raw["manual_input_warnings"]))

    def test_validate_raw_submission(self) -> None:
        valid = {
            "submission_id": "S1",
            "journal_homepage_url": "https://journal.example",
            "publication_model": "issue_based",
            "source_urls": {
                "open_access_statement": ["https://journal.example/open-access"],
                "issn_consistency": ["https://journal.example/about"],
                "publisher_identity": ["https://journal.example/publisher"],
                "license_terms": ["https://journal.example/licensing"],
                "copyright_author_rights": ["https://journal.example/copyright"],
                "peer_review_policy": ["https://journal.example/peer-review"],
                "aims_scope": ["https://journal.example/aims-scope"],
                "editorial_board": ["https://journal.example/editorial-board"],
                "latest_content": ["https://journal.example/issue-1"],
                "instructions_for_authors": ["https://journal.example/instructions"],
                "publication_fees_disclosure": ["https://journal.example/apc"],
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

    def test_run_submission_writes_summary_txt_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            app = SimulationApp(ruleset_path=RULESET_PATH, runs_dir=runs_dir)

            payload = {
                "submission_id": "SIM-ART-1",
                "journal_homepage_url": "https://journal.example",
                "publication_model": "issue_based",
                "open_access_statement": "https://journal.example/open-access",
                "issn_consistency": "https://journal.example/about",
                "publisher_identity": "https://journal.example/publisher",
                "license_terms": "https://journal.example/licensing",
                "copyright_author_rights": "https://journal.example/copyright",
                "peer_review_policy": "https://journal.example/peer-review",
                "aims_scope": "https://journal.example/aims-scope",
                "editorial_board": "https://journal.example/editorial-board",
                "latest_content": "https://journal.example/issue-1",
                "instructions_for_authors": "https://journal.example/instructions",
                "publication_fees_disclosure": "https://journal.example/apc",
            }

            fake_structured = {
                "submission_id": "SIM-ART-1",
                "journal_homepage_url": "https://journal.example",
                "publication_model": "issue_based",
                "crawl_timestamp_utc": "2026-02-16T00:00:00Z",
                "source_urls": {},
                "role_people": [],
                "units": [],
                "evidence": [],
                "policy_pages": [],
            }
            fake_summary = {
                "submission_id": "SIM-ART-1",
                "ruleset_id": "doaj.must.v1",
                "overall_result": "pass",
                "checks": [],
                "supplementary_checks": [],
            }
            fake_endogeny = {
                "rule_id": "doaj.endogeny.v1",
                "result": "pass",
                "confidence": 0.9,
                "crawl_timestamp_utc": "2026-02-16T00:00:00Z",
                "explanation_en": "Endogeny is within threshold.",
                "computed_metrics": {"units": []},
                "matched_articles": [],
                "evidence": [],
                "limitations": [],
            }

            with patch("doaj_reviewer.sim_server.build_structured_submission_from_raw", return_value=fake_structured):
                with patch("doaj_reviewer.sim_server.run_review", return_value=(fake_summary, fake_endogeny)):
                    result = app.run_submission(payload)

            self.assertTrue(result["ok"])
            self.assertIn("summary_txt", result["artifacts"])
            run_id = str(result["run_id"])
            summary_txt = runs_dir / run_id / "review-summary.txt"
            self.assertTrue(summary_txt.exists())

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

    def test_export_csv_includes_problem_urls_for_flagged_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            run_dir = runs_dir / "20260216-ccc33333"
            run_dir.mkdir(parents=True, exist_ok=True)

            (run_dir / "submission.raw.json").write_text(
                json.dumps(
                    {
                        "submission_id": "SIM-FLAGGED",
                        "journal_homepage_url": "https://journal.example",
                        "source_urls": {
                            "open_access_statement": ["https://journal.example/open-access"],
                            "aims_scope": ["https://journal.example/aims-scope"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "review-summary.json").write_text(
                json.dumps(
                    {
                        "submission_id": "SIM-FLAGGED",
                        "overall_result": "fail",
                        "overall_decision_reason": "At least one must-rule returned fail.",
                        "checks": [
                            {
                                "rule_id": "doaj.open_access_statement.v1",
                                "result": "need_human_review",
                                "notes": "Policy text is ambiguous.",
                                "evidence_urls": ["https://journal.example/open-access"],
                            },
                            {
                                "rule_id": "doaj.aims_scope.v1",
                                "result": "fail",
                                "notes": "Aims and scope statement missing.",
                                "source_urls": ["https://journal.example/aims-scope"],
                                "evidence_urls": [],
                            },
                        ],
                        "supplementary_checks": [
                            {
                                "rule_id": "doaj.plagiarism_policy.v1",
                                "result": "need_human_review",
                                "notes": "Similarity threshold not explicit.",
                                "evidence_urls": ["https://journal.example/plagiarism"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            app = SimulationApp(ruleset_path=RULESET_PATH, runs_dir=runs_dir)
            content = app.render_export_csv(limit=None)
            rows = list(csv.DictReader(io.StringIO(content)))
            self.assertEqual(len(rows), 1)
            row = rows[0]

            self.assertEqual(row["overall_result"], "fail")
            self.assertEqual(row["overall_decision_reason"], "At least one must-rule returned fail.")
            self.assertEqual(row["doaj.open_access_statement.v1"], "need_human_review")
            self.assertIn("Policy text is ambiguous.", row["doaj.open_access_statement.v1__note"])
            self.assertIn("https://journal.example/open-access", row["doaj.open_access_statement.v1__problem_urls"])
            self.assertEqual(row["doaj.aims_scope.v1"], "fail")
            self.assertIn("https://journal.example/aims-scope", row["doaj.aims_scope.v1__problem_urls"])
            self.assertIn("doaj.aims_scope.v1:fail", row["must_attention_rules"])
            self.assertIn("doaj.open_access_statement.v1:need_human_review", row["must_attention_rules"])
            self.assertIn("doaj.plagiarism_policy.v1:need_human_review", row["supplementary_attention_rules"])

    def test_export_csv_uses_endogeny_fallback_urls_from_raw_submission(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            run_dir = runs_dir / "20260216-ddd44444"
            run_dir.mkdir(parents=True, exist_ok=True)

            (run_dir / "submission.raw.json").write_text(
                json.dumps(
                    {
                        "submission_id": "SIM-ENDO-FALLBACK",
                        "journal_homepage_url": "https://journal.example",
                        "source_urls": {
                            "latest_content": [
                                "https://journal.example/issue-1",
                                "https://journal.example/issue-2",
                            ],
                            "archives": ["https://journal.example/archive"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "review-summary.json").write_text(
                json.dumps(
                    {
                        "submission_id": "SIM-ENDO-FALLBACK",
                        "overall_result": "fail",
                        "checks": [
                            {
                                "rule_id": "doaj.endogeny.v1",
                                "result": "fail",
                                "notes": "Endogeny exceeds threshold.",
                                "evidence_urls": [],
                            }
                        ],
                        "supplementary_checks": [],
                    }
                ),
                encoding="utf-8",
            )

            app = SimulationApp(ruleset_path=RULESET_PATH, runs_dir=runs_dir)
            content = app.render_export_csv(limit=None)
            rows = list(csv.DictReader(io.StringIO(content)))
            self.assertEqual(len(rows), 1)
            row = rows[0]

            self.assertEqual(row["doaj.endogeny.v1"], "fail")
            self.assertIn("https://journal.example/issue-1", row["doaj.endogeny.v1__problem_urls"])
            self.assertIn("https://journal.example/archive", row["doaj.endogeny.v1__problem_urls"])


if __name__ == "__main__":
    unittest.main()
