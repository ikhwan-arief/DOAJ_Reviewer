from __future__ import annotations

from pathlib import Path
import tempfile
import textwrap
import unittest

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
                    submission_id,journal_homepage_url,publication_model,editorial_board_urls,reviewers_urls,latest_content_urls,archives_urls,open_access_statement_urls,aims_scope_urls,instructions_for_authors_urls,peer_review_policy_urls,license_terms_urls,copyright_author_rights_urls,publication_fees_disclosure_urls,publisher_identity_urls,issn_consistency_urls
                    B1,https://journal.example,issue_based,https://journal.example/editorial-board,,https://journal.example/issue-2|https://journal.example/issue-1,,,,,,,,,,
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


if __name__ == "__main__":
    unittest.main()
