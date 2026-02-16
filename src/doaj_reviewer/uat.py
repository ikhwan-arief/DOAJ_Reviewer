"""Deterministic UAT scenario runner for DOAJ Reviewer."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from .review import render_review_summary_markdown, render_review_summary_text, run_review


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULESET_PATH = REPO_ROOT / "specs" / "reviewer" / "rules" / "ruleset.must.v1.json"
DEFAULT_BASE_SUBMISSION = REPO_ROOT / "examples" / "submission.example.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)


def _scenario_pass(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    payload["submission_id"] = "UAT-PASS-001"
    return payload


def _scenario_need_human_review_waf(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    payload["submission_id"] = "UAT-WAF-NEED-HUMAN-001"
    payload["policy_pages"] = [
        item
        for item in payload.get("policy_pages", [])
        if isinstance(item, dict) and str(item.get("rule_hint", "")) != "open_access_statement"
    ]
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
    evidence.append(
        {
            "kind": "crawl_note",
            "url": "https://example-journal.org/open-access",
            "excerpt": "WAF/anti-bot challenge detected (cloudflare): checking your browser before accessing.",
            "locator_hint": "policy-waf-blocked-open_access_statement",
        }
    )
    payload["evidence"] = evidence
    return payload


def _scenario_fail_reviewer_composition(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    payload["submission_id"] = "UAT-REVIEWER-COMPOSITION-FAIL-001"

    source_urls = payload.get("source_urls", {})
    if not isinstance(source_urls, dict):
        source_urls = {}
    source_urls["reviewers"] = ["https://example-journal.org/reviewers"]
    payload["source_urls"] = source_urls

    role_people = payload.get("role_people", [])
    if not isinstance(role_people, list):
        role_people = []
    role_people = [item for item in role_people if not (isinstance(item, dict) and str(item.get("role", "")) == "reviewer")]
    for idx in range(1, 11):
        role_people.append(
            {
                "name": f"Reviewer Internal {idx}",
                "role": "reviewer",
                "source_url": "https://example-journal.org/reviewers",
                "affiliation": "Example University Press",
            }
        )
    payload["role_people"] = role_people

    policy_pages = payload.get("policy_pages", [])
    if not isinstance(policy_pages, list):
        policy_pages = []
    has_reviewer_page = any(
        isinstance(item, dict)
        and str(item.get("rule_hint", "")) == "editorial_board"
        and "reviewer" in str(item.get("title", "")).lower()
        for item in policy_pages
    )
    if not has_reviewer_page:
        policy_pages.append(
            {
                "rule_hint": "editorial_board",
                "url": "https://example-journal.org/reviewers",
                "title": "Reviewers",
                "text": "Reviewer list with affiliations is provided.",
            }
        )
    payload["policy_pages"] = policy_pages
    return payload


def build_uat_scenarios(base_submission: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "S1_PASS_BASELINE",
            "name": "Baseline must-pass example",
            "expected_overall": "pass",
            "submission": _scenario_pass(base_submission),
        },
        {
            "id": "S2_NEED_HUMAN_WAF",
            "name": "Policy page blocked by WAF challenge",
            "expected_overall": "need_human_review",
            "submission": _scenario_need_human_review_waf(base_submission),
        },
        {
            "id": "S3_FAIL_REVIEWER_COMPOSITION",
            "name": "Reviewer composition violates threshold",
            "expected_overall": "fail",
            "submission": _scenario_fail_reviewer_composition(base_submission),
        },
    ]


def _render_uat_markdown(rows: list[dict[str, Any]], ruleset_path: Path) -> str:
    lines: list[str] = []
    lines.append("# UAT Scenario Report")
    lines.append("")
    lines.append(f"- Ruleset: `{ruleset_path}`")
    lines.append("")
    lines.append("| Scenario ID | Scenario | Expected | Actual | Match |")
    lines.append("|---|---|---|---|---|")
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("scenario_id", "")),
                    str(row.get("scenario_name", "")),
                    str(row.get("expected", "")),
                    str(row.get("actual", "")),
                    "yes" if row.get("is_match", False) else "no",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def run_uat_scenarios(
    output_dir: Path,
    ruleset_path: Path = DEFAULT_RULESET_PATH,
    base_submission_path: Path = DEFAULT_BASE_SUBMISSION,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ruleset = _load_json(ruleset_path)
    base_submission = _load_json(base_submission_path)
    scenarios = build_uat_scenarios(base_submission)

    rows: list[dict[str, Any]] = []
    all_match = True
    for scenario in scenarios:
        scenario_id = str(scenario["id"])
        submission = copy.deepcopy(scenario["submission"])
        summary, endogeny = run_review(submission=submission, ruleset=ruleset)
        actual = str(summary.get("overall_result", "need_human_review"))
        expected = str(scenario["expected_overall"])
        is_match = actual == expected
        all_match = all_match and is_match

        scenario_dir = output_dir / scenario_id
        _write_json(scenario_dir / "review-summary.json", summary)
        _write_text(scenario_dir / "review-summary.md", render_review_summary_markdown(summary))
        _write_text(scenario_dir / "review-summary.txt", render_review_summary_text(summary))
        _write_json(scenario_dir / "endogeny-result.json", endogeny)

        rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_name": str(scenario["name"]),
                "expected": expected,
                "actual": actual,
                "is_match": is_match,
            }
        )

    report = {
        "ok": all_match,
        "scenario_count": len(rows),
        "matched_count": len([row for row in rows if row["is_match"]]),
        "rows": rows,
    }
    _write_json(output_dir / "uat-report.json", report)
    _write_text(output_dir / "uat-report.md", _render_uat_markdown(rows, ruleset_path=ruleset_path))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic UAT scenarios for DOAJ Reviewer.")
    parser.add_argument("--output-dir", default="artifacts/uat", help="Directory to store UAT output artifacts.")
    parser.add_argument("--ruleset", default=str(DEFAULT_RULESET_PATH), help="Path to ruleset JSON.")
    parser.add_argument("--base-submission", default=str(DEFAULT_BASE_SUBMISSION), help="Path to base structured submission JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_uat_scenarios(
        output_dir=Path(args.output_dir),
        ruleset_path=Path(args.ruleset),
        base_submission_path=Path(args.base_submission),
    )
    print(f"UAT scenarios: {report.get('scenario_count', 0)}")
    print(f"Matched expectation: {report.get('matched_count', 0)}")
    print(f"Overall UAT status: {'PASS' if report.get('ok', False) else 'FAIL'}")
    print(f"Output: {args.output_dir}")
    return 0 if bool(report.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

