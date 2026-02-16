from __future__ import annotations

import unittest

from doaj_reviewer.basic_rules import (
    evaluate_aims_scope,
    evaluate_copyright_author_rights,
    evaluate_editorial_board,
    evaluate_issn_consistency,
    evaluate_instructions_for_authors,
    evaluate_license_terms,
    evaluate_open_access_statement,
    evaluate_peer_review_policy,
    evaluate_publisher_identity,
    evaluate_publication_fees_disclosure,
)


def _submission_with_policy_pages(policy_pages):
    return {
        "submission_id": "BASIC-1",
        "journal_homepage_url": "https://example.org",
        "publication_model": "issue_based",
        "source_urls": {
            "editorial_board": ["https://example.org/editorial-board"],
            "open_access_statement": ["https://example.org/open-access"],
            "issn_consistency": ["https://example.org/about"],
            "publisher_identity": ["https://example.org/publisher"],
            "license_terms": ["https://example.org/licensing"],
            "copyright_author_rights": ["https://example.org/copyright"],
            "peer_review_policy": ["https://example.org/peer-review"],
            "plagiarism_policy": [],
            "aims_scope": ["https://example.org/aims-and-scope"],
            "publication_fees_disclosure": ["https://example.org/apc"],
            "archiving_policy": [],
            "repository_policy": [],
            "reviewers": [],
            "latest_content": ["https://example.org/issue-1", "https://example.org/issue-2"],
            "instructions_for_authors": ["https://example.org/instructions"],
            "archives": [],
        },
        "role_people": [
            {
                "name": "Dr Jane Smith",
                "role": "editor",
                "source_url": "https://example.org/editorial-board",
                "affiliation": "Example University",
            },
            {
                "name": "Asep Rahman",
                "role": "editorial_board_member",
                "source_url": "https://example.org/editorial-board",
                "affiliation": "Institute A",
            },
            {
                "name": "Lina Putri",
                "role": "editorial_board_member",
                "source_url": "https://example.org/editorial-board",
                "affiliation": "Institute B",
            },
            {
                "name": "Dwi Prasetyo",
                "role": "editorial_board_member",
                "source_url": "https://example.org/editorial-board",
                "affiliation": "Institute C",
            },
            {
                "name": "Rina Lestari",
                "role": "editorial_board_member",
                "source_url": "https://example.org/editorial-board",
                "affiliation": "Institute D",
            },
        ],
        "policy_pages": policy_pages,
    }


class BasicRuleTests(unittest.TestCase):
    def test_open_access_pass(self) -> None:
        submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "open_access_statement",
                    "url": "https://example.org/open-access",
                    "title": "Open Access",
                    "text": "This is an open access journal. Users may read, download, copy, distribute and reuse articles under Creative Commons CC BY.",
                }
            ]
        )
        result = evaluate_open_access_statement(submission)
        self.assertEqual(result["result"], "pass")

    def test_open_access_fail_when_subscription_only(self) -> None:
        submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "open_access_statement",
                    "url": "https://example.org/open-access",
                    "title": "Access Policy",
                    "text": "Access limited to subscribers and members only. Subscription required for full-text access.",
                }
            ]
        )
        result = evaluate_open_access_statement(submission)
        self.assertEqual(result["result"], "fail")

    def test_missing_policy_mentions_waf_block(self) -> None:
        submission = _submission_with_policy_pages([])
        submission["source_urls"]["open_access_statement"] = ["https://example.org/open-access"]
        submission["evidence"] = [
            {
                "kind": "crawl_note",
                "url": "https://example.org/open-access",
                "excerpt": "WAF/anti-bot challenge detected (cloudflare): checking your browser before accessing.",
                "locator_hint": "policy-waf-blocked-open_access_statement",
            }
        ]
        result = evaluate_open_access_statement(submission)
        self.assertEqual(result["result"], "need_human_review")
        self.assertIn("WAF/anti-bot challenge", result["notes"])

    def test_peer_review_pass(self) -> None:
        submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "peer_review_policy",
                    "url": "https://example.org/peer-review",
                    "title": "Peer Review",
                    "text": "All manuscripts are peer reviewed with double blind process. At least two independent reviewers evaluate each article before editorial decision.",
                }
            ]
        )
        result = evaluate_peer_review_policy(submission)
        self.assertEqual(result["result"], "pass")

    def test_peer_review_needs_human_when_two_reviewers_not_explicit(self) -> None:
        submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "peer_review_policy",
                    "url": "https://example.org/peer-review",
                    "title": "Peer Review",
                    "text": "The journal applies peer review and editorial decision process for each submission.",
                }
            ]
        )
        result = evaluate_peer_review_policy(submission)
        self.assertEqual(result["result"], "need_human_review")

    def test_license_pass_and_fail_paths(self) -> None:
        pass_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "license_terms",
                    "url": "https://example.org/licensing",
                    "title": "Licensing",
                    "text": "Articles are published under Creative Commons CC BY 4.0 license.",
                }
            ]
        )
        fail_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "license_terms",
                    "url": "https://example.org/licensing",
                    "title": "Copyright",
                    "text": "All rights reserved. No license is granted for redistribution.",
                }
            ]
        )

        self.assertEqual(evaluate_license_terms(pass_submission)["result"], "pass")
        self.assertEqual(evaluate_license_terms(fail_submission)["result"], "fail")

    def test_copyright_author_rights_pass_and_fail_paths(self) -> None:
        pass_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "copyright_author_rights",
                    "url": "https://example.org/copyright",
                    "title": "Copyright",
                    "text": "Authors retain copyright and grant a non-exclusive license to publish.",
                }
            ]
        )
        fail_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "copyright_author_rights",
                    "url": "https://example.org/copyright",
                    "title": "Copyright",
                    "text": "Authors transfer copyright to the publisher and assign exclusive rights.",
                }
            ]
        )
        self.assertEqual(evaluate_copyright_author_rights(pass_submission)["result"], "pass")
        self.assertEqual(evaluate_copyright_author_rights(fail_submission)["result"], "fail")

    def test_publication_fees_disclosure_pass_paths(self) -> None:
        apc_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "publication_fees_disclosure",
                    "url": "https://example.org/apc",
                    "title": "APC",
                    "text": "The journal charges an article processing charge (APC) of USD 100.",
                }
            ]
        )
        no_fee_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "publication_fees_disclosure",
                    "url": "https://example.org/apc",
                    "title": "Fees",
                    "text": "The journal does not charge any publication fee and has no APC.",
                }
            ]
        )
        self.assertEqual(evaluate_publication_fees_disclosure(apc_submission)["result"], "pass")
        self.assertEqual(evaluate_publication_fees_disclosure(no_fee_submission)["result"], "pass")

    def test_publisher_identity_pass(self) -> None:
        submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "publisher_identity",
                    "url": "https://example.org/publisher",
                    "title": "Publisher",
                    "text": "Publisher: Example University Press. Contact: editor@example.org. Address: City, Country.",
                }
            ]
        )
        result = evaluate_publisher_identity(submission)
        self.assertEqual(result["result"], "pass")

    def test_issn_consistency_pass_and_fail(self) -> None:
        pass_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "issn_consistency",
                    "url": "https://example.org/about",
                    "title": "About",
                    "text": "ISSN (Print): 1234-5679. ISSN (Online): 2049-3630.",
                }
            ]
        )
        fail_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "issn_consistency",
                    "url": "https://example.org/about",
                    "title": "About",
                    "text": "ISSN: 1234-5678",
                }
            ]
        )
        self.assertEqual(evaluate_issn_consistency(pass_submission)["result"], "pass")
        self.assertEqual(evaluate_issn_consistency(fail_submission)["result"], "fail")

    def test_aims_scope_and_instructions_pass(self) -> None:
        aims_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "aims_scope",
                    "url": "https://example.org/aims-and-scope",
                    "title": "Aims and Scope",
                    "text": "Aims and Scope: The journal publishes research articles in informatics and digital policy.",
                }
            ]
        )
        inst_submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "instructions_for_authors",
                    "url": "https://example.org/instructions",
                    "title": "Instructions for Authors",
                    "text": "Instructions for Authors include manuscript format, submission guidelines, template, ethics and peer review process.",
                }
            ]
        )
        self.assertEqual(evaluate_aims_scope(aims_submission)["result"], "pass")
        self.assertEqual(evaluate_instructions_for_authors(inst_submission)["result"], "pass")

    def test_editorial_board_pass(self) -> None:
        submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "editorial_board",
                    "url": "https://example.org/editorial-board",
                    "title": "Editorial Board",
                    "text": "Editor in Chief and editorial board members with university affiliations are listed.",
                }
            ]
        )
        result = evaluate_editorial_board(submission)
        self.assertEqual(result["result"], "pass")

    def test_editorial_board_leniency_with_reviewer_composition_pass(self) -> None:
        submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "editorial_board",
                    "url": "https://example.org/editorial-board",
                    "title": "Editorial Board",
                    "text": "Editor in Chief and editorial board members with affiliations are listed.",
                },
                {
                    "rule_hint": "reviewers",
                    "url": "https://example.org/reviewers",
                    "title": "Reviewers",
                    "text": "Reviewer list and affiliations.",
                },
                {
                    "rule_hint": "publisher_identity",
                    "url": "https://example.org/publisher",
                    "title": "Publisher",
                    "text": "Publisher: Example University Press. Address: City, Country.",
                },
            ]
        )
        submission["source_urls"]["reviewers"] = ["https://example.org/reviewers"]
        for item in submission["role_people"]:
            if item["role"] in {"editor", "editorial_board_member"}:
                item["affiliation"] = "Example University Press"

        reviewer_people = []
        for idx in range(1, 5):
            reviewer_people.append(
                {
                    "name": f"Reviewer Same {idx}",
                    "role": "reviewer",
                    "source_url": "https://example.org/reviewers",
                    "affiliation": "Example University Press",
                }
            )
        for idx in range(1, 7):
            reviewer_people.append(
                {
                    "name": f"Reviewer Outside {idx}",
                    "role": "reviewer",
                    "source_url": "https://example.org/reviewers",
                    "affiliation": f"Institute Outside {idx}",
                }
            )
        submission["role_people"].extend(reviewer_people)

        result = evaluate_editorial_board(submission)
        self.assertEqual(result["result"], "pass")
        self.assertIn("Editorial board affiliation composition (informational only)", result["notes"])
        self.assertIn("Reviewer composition meets target range", result["notes"])

    def test_reviewer_composition_fail_even_if_editorial_board_allowed(self) -> None:
        submission = _submission_with_policy_pages(
            [
                {
                    "rule_hint": "editorial_board",
                    "url": "https://example.org/editorial-board",
                    "title": "Editorial Board",
                    "text": "Editor in Chief and editorial board members with affiliations are listed.",
                },
                {
                    "rule_hint": "reviewers",
                    "url": "https://example.org/reviewers",
                    "title": "Reviewers",
                    "text": "Reviewer list and affiliations.",
                },
                {
                    "rule_hint": "publisher_identity",
                    "url": "https://example.org/publisher",
                    "title": "Publisher",
                    "text": "Publisher: Example University Press. Address: City, Country.",
                },
            ]
        )
        submission["source_urls"]["reviewers"] = ["https://example.org/reviewers"]
        for item in submission["role_people"]:
            if item["role"] in {"editor", "editorial_board_member"}:
                item["affiliation"] = "Example University Press"

        reviewer_people = []
        for idx in range(1, 8):
            reviewer_people.append(
                {
                    "name": f"Reviewer Same {idx}",
                    "role": "reviewer",
                    "source_url": "https://example.org/reviewers",
                    "affiliation": "Example University Press",
                }
            )
        for idx in range(1, 4):
            reviewer_people.append(
                {
                    "name": f"Reviewer Outside {idx}",
                    "role": "reviewer",
                    "source_url": "https://example.org/reviewers",
                    "affiliation": f"Institute Outside {idx}",
                }
            )
        submission["role_people"].extend(reviewer_people)

        result = evaluate_editorial_board(submission)
        self.assertEqual(result["result"], "fail")
        self.assertIn("Reviewer affiliation composition is outside target range", result["notes"])


if __name__ == "__main__":
    unittest.main()
