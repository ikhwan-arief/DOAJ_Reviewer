from __future__ import annotations

from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from doaj_reviewer.spreadsheet_batch import run_batch


class SpreadsheetBatchTests(unittest.TestCase):
    def test_convert_only_generates_raw_json_and_overview(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "batch.csv"
            out_dir = root / "out"

            csv_path.write_text(
                textwrap.dedent(
                    """\
                    submission_id,journal_homepage_url,publication_model,open_access_statement_urls,issn_consistency_urls,publisher_identity_urls,license_terms_urls,copyright_author_rights_urls,peer_review_policy_urls,plagiarism_policy_urls,aims_scope_urls,editorial_board_urls,reviewers_urls,latest_content_urls,instructions_for_authors_urls,publication_fees_disclosure_urls,archiving_policy_urls,repository_policy_urls,archives_urls
                    B1,https://journal.example,issue_based,https://journal.example/open-access,https://journal.example/about,https://journal.example/publisher,https://journal.example/licensing,https://journal.example/copyright,https://journal.example/peer-review,,https://journal.example/aims-scope,https://journal.example/editorial-board,,https://journal.example/issue-2|https://journal.example/issue-1,https://journal.example/instructions,https://journal.example/apc,,,
                    """
                ),
                encoding="utf-8",
            )

            count = run_batch(
                input_csv=csv_path,
                output_dir=out_dir,
                ruleset_path=Path("specs/reviewer/rules/ruleset.must.v1.json"),
                convert_only=True,
            )

            self.assertEqual(count, 1)
            self.assertTrue((out_dir / "B1" / "submission.raw.json").exists())
            self.assertTrue((out_dir / "overview.csv").exists())
            self.assertFalse((out_dir / "B1" / "submission.structured.json").exists())

    def test_full_run_writes_summary_txt_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "batch.csv"
            out_dir = root / "out"

            csv_path.write_text(
                textwrap.dedent(
                    """\
                    submission_id,journal_homepage_url,publication_model,open_access_statement_urls,issn_consistency_urls,publisher_identity_urls,license_terms_urls,copyright_author_rights_urls,peer_review_policy_urls,plagiarism_policy_urls,aims_scope_urls,editorial_board_urls,reviewers_urls,latest_content_urls,instructions_for_authors_urls,publication_fees_disclosure_urls,archiving_policy_urls,repository_policy_urls,archives_urls
                    B2,https://journal.example,issue_based,https://journal.example/open-access,https://journal.example/about,https://journal.example/publisher,https://journal.example/licensing,https://journal.example/copyright,https://journal.example/peer-review,,https://journal.example/aims-scope,https://journal.example/editorial-board,,https://journal.example/issue-2|https://journal.example/issue-1,https://journal.example/instructions,https://journal.example/apc,,,
                    """
                ),
                encoding="utf-8",
            )

            fake_structured = {
                "submission_id": "B2",
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
                "submission_id": "B2",
                "ruleset_id": "doaj.must.v1",
                "ruleset_version": "1.0.0",
                "generated_at_utc": "2026-02-16T00:00:10Z",
                "overall_result": "pass",
                "overall_decision_reason": "All must-rules passed automatically.",
                "must_result_counts": {"pass": 1, "fail": 0, "need_human_review": 0, "not_provided": 0, "other": 0},
                "supplementary_result_counts": {"pass": 0, "fail": 0, "need_human_review": 0, "not_provided": 0, "other": 0},
                "traceability": {
                    "total_source_urls_submitted": 0,
                    "total_policy_pages_extracted": 0,
                    "total_crawl_notes": 0,
                    "source_url_coverage": [],
                },
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

            with patch("doaj_reviewer.spreadsheet_batch.build_structured_submission_from_raw", return_value=fake_structured):
                with patch("doaj_reviewer.spreadsheet_batch.run_review", return_value=(fake_summary, fake_endogeny)):
                    count = run_batch(
                        input_csv=csv_path,
                        output_dir=out_dir,
                        ruleset_path=Path("specs/reviewer/rules/ruleset.must.v1.json"),
                        convert_only=False,
                    )

            self.assertEqual(count, 1)
            summary_txt = out_dir / "B2" / "review-summary.txt"
            self.assertTrue(summary_txt.exists())
            self.assertIn("DOAJ Reviewer Summary", summary_txt.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
