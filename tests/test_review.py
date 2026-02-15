from __future__ import annotations

import json
from pathlib import Path
import unittest

from doaj_reviewer.review import run_review


class ReviewRunnerTests(unittest.TestCase):
    def test_ruleset_summary_all_implemented_checks_can_pass(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        ruleset_path = repo_root / "specs" / "reviewer" / "rules" / "ruleset.must.v1.json"
        submission_path = repo_root / "examples" / "submission.example.json"

        with ruleset_path.open("r", encoding="utf-8") as f:
            ruleset = json.load(f)
        with submission_path.open("r", encoding="utf-8") as f:
            submission = json.load(f)

        summary, endogeny = run_review(submission=submission, ruleset=ruleset)

        self.assertEqual(endogeny["result"], "pass")
        self.assertEqual(summary["overall_result"], "pass")
        self.assertGreater(len(summary["checks"]), 1)
        self.assertTrue(any(item["rule_id"] == "doaj.endogeny.v1" for item in summary["checks"]))
        by_rule = {item["rule_id"]: item for item in summary["checks"]}
        self.assertEqual(by_rule["doaj.open_access_statement.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.aims_scope.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.editorial_board.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.instructions_for_authors.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.peer_review_policy.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.license_terms.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.copyright_author_rights.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.publication_fees_disclosure.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.publisher_identity.v1"]["result"], "pass")
        self.assertEqual(by_rule["doaj.issn_consistency.v1"]["result"], "pass")


if __name__ == "__main__":
    unittest.main()
