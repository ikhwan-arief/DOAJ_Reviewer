from __future__ import annotations

from copy import deepcopy
import unittest

from doaj_reviewer.endogeny import evaluate_endogeny


def _base_submission() -> dict:
    return {
        "submission_id": "T-1",
        "journal_homepage_url": "https://example.org",
        "publication_model": "issue_based",
        "source_urls": {
            "editorial_board": ["https://example.org/editorial-board"],
            "latest_content": ["https://example.org/issue-2", "https://example.org/issue-1"],
            "reviewers": ["https://example.org/reviewers"],
        },
        "role_people": [
            {"name": "Dr. Jane Smith", "role": "editor", "source_url": "https://example.org/editorial-board"},
            {"name": "Lina Putri", "role": "reviewer", "source_url": "https://example.org/reviewers"},
        ],
        "units": [
            {
                "label": "Issue 2",
                "window_type": "issue",
                "source_url": "https://example.org/issue-2",
                "research_articles": [
                    {"title": "A", "url": "https://example.org/a", "authors": ["Jane Smith"]},
                    {"title": "B", "url": "https://example.org/b", "authors": ["Author B"]},
                    {"title": "C", "url": "https://example.org/c", "authors": ["Author C"]},
                    {"title": "D", "url": "https://example.org/d", "authors": ["Author D"]},
                ],
            },
            {
                "label": "Issue 1",
                "window_type": "issue",
                "source_url": "https://example.org/issue-1",
                "research_articles": [
                    {"title": "E", "url": "https://example.org/e", "authors": ["L. Putri"]},
                    {"title": "F", "url": "https://example.org/f", "authors": ["Author F"]},
                    {"title": "G", "url": "https://example.org/g", "authors": ["Author G"]},
                    {"title": "H", "url": "https://example.org/h", "authors": ["Author H"]},
                ],
            },
        ],
    }


class EndogenyEvaluatorTests(unittest.TestCase):
    def test_pass_when_each_issue_is_25_percent(self) -> None:
        submission = _base_submission()
        result = evaluate_endogeny(submission)

        self.assertEqual(result["result"], "pass")
        self.assertEqual(result["computed_metrics"]["max_ratio_observed"], 0.25)
        self.assertTrue(result["computed_metrics"]["all_units_within_threshold"])

    def test_fail_when_any_issue_exceeds_threshold(self) -> None:
        submission = _base_submission()
        submission["units"][1]["research_articles"][1]["authors"] = ["Dr Jane Smith"]

        result = evaluate_endogeny(submission)

        self.assertEqual(result["result"], "fail")
        self.assertGreater(result["computed_metrics"]["max_ratio_observed"], 0.25)

    def test_need_human_review_with_missing_second_issue(self) -> None:
        submission = _base_submission()
        submission["units"] = submission["units"][:1]

        result = evaluate_endogeny(submission)

        self.assertEqual(result["result"], "need_human_review")
        self.assertIn("Latest two issues are not fully available.", result["limitations"])

    def test_need_human_review_for_continuous_below_minimum_articles(self) -> None:
        submission = _base_submission()
        submission["publication_model"] = "continuous"
        submission["units"] = [
            {
                "label": "2025",
                "window_type": "calendar_year",
                "source_url": "https://example.org/2025",
                "research_articles": [
                    {"title": "A", "url": "https://example.org/a", "authors": ["Jane Smith"]},
                    {"title": "B", "url": "https://example.org/b", "authors": ["Author B"]},
                    {"title": "C", "url": "https://example.org/c", "authors": ["Author C"]},
                    {"title": "D", "url": "https://example.org/d", "authors": ["Author D"]},
                ],
            }
        ]

        result = evaluate_endogeny(submission)

        self.assertEqual(result["result"], "need_human_review")
        self.assertIn(
            "Continuous model has fewer than 5 research articles in the last calendar year.",
            result["limitations"],
        )

    def test_need_human_review_when_no_eligible_role_people(self) -> None:
        submission = _base_submission()
        submission["role_people"] = [
            {"name": "Alex Staff", "role": "assistant", "source_url": "https://example.org/editorial-board"}
        ]

        result = evaluate_endogeny(submission)

        self.assertEqual(result["result"], "need_human_review")
        self.assertIn(
            "No eligible editor/editorial board member/reviewer names were available for matching.",
            result["limitations"],
        )

    def test_non_eligible_roles_are_ignored_in_matching(self) -> None:
        submission = _base_submission()
        submission["role_people"] = [
            {"name": "Alex Staff", "role": "assistant", "source_url": "https://example.org/editorial-board"},
            {"name": "Dr. Jane Smith", "role": "editor", "source_url": "https://example.org/editorial-board"},
        ]
        submission["units"][0]["research_articles"][0]["authors"] = ["Alex Staff"]
        submission["units"][0]["research_articles"][1]["authors"] = ["Dr. Jane Smith"]

        result = evaluate_endogeny(submission)

        self.assertEqual(result["computed_metrics"]["units"][0]["matched_article_count"], 1)
        matched_roles = {item.get("matched_role", "") for item in result.get("matched_articles", [])}
        self.assertNotIn("assistant", matched_roles)


if __name__ == "__main__":
    unittest.main()
