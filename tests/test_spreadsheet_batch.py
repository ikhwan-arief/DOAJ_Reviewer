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


if __name__ == "__main__":
    unittest.main()
