"""Deterministic golden dataset runner for DOAJ Reviewer regression checks."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Callable

from .review import render_review_summary_markdown, render_review_summary_text, run_review


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULESET_PATH = REPO_ROOT / "specs" / "reviewer" / "rules" / "ruleset.must.v1.json"
DEFAULT_BASE_SUBMISSION = REPO_ROOT / "examples" / "submission.example.json"
DEFAULT_CASES_PATH = REPO_ROOT / "specs" / "reviewer" / "golden" / "golden-cases.v1.json"

ScenarioBuilder = Callable[[dict[str, Any]], dict[str, Any]]


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


def _source_urls(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("source_urls", {})
    if not isinstance(raw, dict):
        raw = {}
    payload["source_urls"] = raw
    return raw


def _policy_pages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("policy_pages", [])
    if not isinstance(raw, list):
        raw = []
    pages: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            pages.append(item)
    payload["policy_pages"] = pages
    return pages


def _evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("evidence", [])
    if not isinstance(raw, list):
        raw = []
    evidence: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            evidence.append(item)
    payload["evidence"] = evidence
    return evidence


def _set_rule_urls(payload: dict[str, Any], rule_hint: str, urls: list[str]) -> None:
    source_urls = _source_urls(payload)
    source_urls[rule_hint] = [str(url) for url in urls if isinstance(url, str) and url]


def _default_rule_url(rule_hint: str) -> str:
    return f"https://example-journal.org/{rule_hint.replace('_', '-')}"


def _first_rule_url(payload: dict[str, Any], rule_hint: str) -> str:
    source_urls = _source_urls(payload)
    raw_urls = source_urls.get(rule_hint, [])
    if isinstance(raw_urls, list):
        for item in raw_urls:
            if isinstance(item, str) and item:
                return item
    return _default_rule_url(rule_hint)


def _upsert_policy_page(payload: dict[str, Any], rule_hint: str, title: str, text: str, *, url: str | None = None) -> None:
    pages = _policy_pages(payload)
    page_url = url or _first_rule_url(payload, rule_hint)
    for page in pages:
        if str(page.get("rule_hint", "")) != rule_hint:
            continue
        page["title"] = title
        page["text"] = text
        page["url"] = page_url
        return
    pages.append(
        {
            "rule_hint": rule_hint,
            "url": page_url,
            "title": title,
            "text": text,
        }
    )


def _remove_policy_pages(payload: dict[str, Any], rule_hint: str) -> None:
    pages = _policy_pages(payload)
    payload["policy_pages"] = [page for page in pages if str(page.get("rule_hint", "")) != rule_hint]


def _scenario_baseline_pass(base_submission: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(base_submission)


def _scenario_oa_waf_blocked(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    _set_rule_urls(payload, "open_access_statement", ["https://example-journal.org/open-access"])
    _remove_policy_pages(payload, "open_access_statement")
    _evidence(payload).append(
        {
            "kind": "crawl_note",
            "url": "https://example-journal.org/open-access",
            "excerpt": "WAF/anti-bot challenge detected (cloudflare): checking your browser before accessing.",
            "locator_hint": "policy-waf-blocked-open_access_statement",
        }
    )
    return payload


def _scenario_license_restrictive_fail(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    _upsert_policy_page(
        payload,
        "license_terms",
        "Licensing Terms",
        "All rights reserved. No license is granted for reuse, distribution, or adaptation. Subscription required.",
        url="https://example-journal.org/licensing",
    )
    return payload


def _scenario_issn_invalid_electronic_fail(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    _upsert_policy_page(
        payload,
        "issn_consistency",
        "About the Journal",
        "E-ISSN: 2049-3631.",
        url="https://example-journal.org/about",
    )
    return payload


def _scenario_peer_review_missing_two(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    _upsert_policy_page(
        payload,
        "peer_review_policy",
        "Peer Review",
        (
            "All submitted manuscripts are peer reviewed. "
            "The journal uses double blind peer review by external reviewers before editorial decision."
        ),
        url="https://example-journal.org/peer-review",
    )
    return payload


def _scenario_aims_scope_scope_only(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    _upsert_policy_page(
        payload,
        "aims_scope",
        "Journal Scope",
        "Journal Scope: The journal publishes research in information systems, software engineering, and data science.",
        url="https://example-journal.org/aims-and-scope",
    )
    return payload


def _scenario_reviewer_composition_fail(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    reviewer_url = "https://example-journal.org/reviewers"
    _set_rule_urls(payload, "reviewers", [reviewer_url])

    role_people = payload.get("role_people", [])
    if not isinstance(role_people, list):
        role_people = []
    updated_people = [
        item for item in role_people if not (isinstance(item, dict) and str(item.get("role", "")) == "reviewer")
    ]
    for idx in range(1, 11):
        updated_people.append(
            {
                "name": f"Reviewer Internal {idx}",
                "role": "reviewer",
                "source_url": reviewer_url,
                "affiliation": "Example University Press",
            }
        )
    payload["role_people"] = updated_people

    pages = _policy_pages(payload)
    if not any(str(item.get("url", "")) == reviewer_url for item in pages):
        pages.append(
            {
                "rule_hint": "editorial_board",
                "url": reviewer_url,
                "title": "Reviewers",
                "text": "Reviewer list with affiliations is provided.",
            }
        )
    return payload


def _scenario_continuous_under_minimum_articles(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    payload["publication_model"] = "continuous"
    payload["units"] = [
        {
            "label": "Calendar Year 2025",
            "window_type": "calendar_year",
            "source_url": "https://example-journal.org/archive/2025",
            "research_articles": [
                {
                    "title": "Continuous Article A",
                    "url": "https://example-journal.org/2025/a",
                    "authors": ["Alpha One", "Beta Two"],
                },
                {
                    "title": "Continuous Article B",
                    "url": "https://example-journal.org/2025/b",
                    "authors": ["Gamma Three"],
                },
                {
                    "title": "Continuous Article C",
                    "url": "https://example-journal.org/2025/c",
                    "authors": ["Delta Four"],
                },
                {
                    "title": "Continuous Article D",
                    "url": "https://example-journal.org/2025/d",
                    "authors": ["Epsilon Five"],
                }
            ],
        }
    ]
    return payload


def _scenario_issue_endogeny_over_threshold(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    payload["publication_model"] = "issue_based"
    payload["units"] = [
        {
            "label": "Volume 20 Issue 2",
            "window_type": "issue",
            "source_url": "https://example-journal.org/volume-20-issue-2",
            "research_articles": [
                {
                    "title": "Issue Article A",
                    "url": "https://example-journal.org/v20i2/a",
                    "authors": ["Jane Smith", "External Person"],
                },
                {
                    "title": "Issue Article B",
                    "url": "https://example-journal.org/v20i2/b",
                    "authors": ["Dwi Prasetyo", "Another External"],
                },
                {
                    "title": "Issue Article C",
                    "url": "https://example-journal.org/v20i2/c",
                    "authors": ["Independent One"],
                },
                {
                    "title": "Issue Article D",
                    "url": "https://example-journal.org/v20i2/d",
                    "authors": ["Independent Two"],
                }
            ],
        },
        {
            "label": "Volume 20 Issue 1",
            "window_type": "issue",
            "source_url": "https://example-journal.org/volume-20-issue-1",
            "research_articles": [
                {
                    "title": "Issue Article E",
                    "url": "https://example-journal.org/v20i1/e",
                    "authors": ["Independent Three"],
                },
                {
                    "title": "Issue Article F",
                    "url": "https://example-journal.org/v20i1/f",
                    "authors": ["Independent Four"],
                },
                {
                    "title": "Issue Article G",
                    "url": "https://example-journal.org/v20i1/g",
                    "authors": ["Independent Five"],
                },
                {
                    "title": "Issue Article H",
                    "url": "https://example-journal.org/v20i1/h",
                    "authors": ["Independent Six"],
                }
            ],
        }
    ]
    return payload


def _scenario_optional_policies_missing(base_submission: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(base_submission)
    _set_rule_urls(payload, "plagiarism_policy", [])
    _set_rule_urls(payload, "archiving_policy", [])
    _set_rule_urls(payload, "repository_policy", [])
    _remove_policy_pages(payload, "plagiarism_policy")
    _remove_policy_pages(payload, "archiving_policy")
    _remove_policy_pages(payload, "repository_policy")
    return payload


SCENARIO_BUILDERS: dict[str, ScenarioBuilder] = {
    "baseline_pass": _scenario_baseline_pass,
    "oa_waf_blocked": _scenario_oa_waf_blocked,
    "license_restrictive_fail": _scenario_license_restrictive_fail,
    "issn_invalid_electronic_fail": _scenario_issn_invalid_electronic_fail,
    "peer_review_missing_two": _scenario_peer_review_missing_two,
    "aims_scope_scope_only": _scenario_aims_scope_scope_only,
    "reviewer_composition_fail": _scenario_reviewer_composition_fail,
    "continuous_under_minimum_articles": _scenario_continuous_under_minimum_articles,
    "issue_endogeny_over_threshold": _scenario_issue_endogeny_over_threshold,
    "optional_policies_missing": _scenario_optional_policies_missing,
}


def load_case_definitions(path: Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    dataset = _load_json(path)
    cases = dataset.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Golden dataset must contain a list in `cases`.")

    seen_ids: set[str] = set()
    for idx, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Golden case at index {idx} is not an object.")
        case_id = str(case.get("id", "")).strip()
        if not case_id:
            raise ValueError(f"Golden case at index {idx} does not define `id`.")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate golden case id: {case_id}")
        seen_ids.add(case_id)
        scenario = str(case.get("scenario", "")).strip()
        if scenario not in SCENARIO_BUILDERS:
            raise ValueError(f"Golden case `{case_id}` uses unknown scenario `{scenario}`.")
        expected = case.get("expected", {})
        if not isinstance(expected, dict):
            raise ValueError(f"Golden case `{case_id}` has invalid `expected` block.")
    return dataset


def _must_rule_results(summary: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    checks = summary.get("checks", [])
    if not isinstance(checks, list):
        return out
    for item in checks:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id", "")).strip()
        if not rule_id:
            continue
        out[rule_id] = str(item.get("result", "need_human_review"))
    return out


def _supplementary_rule_results(summary: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    checks = summary.get("supplementary_checks", [])
    if not isinstance(checks, list):
        return out
    for item in checks:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id", "")).strip()
        if not rule_id:
            continue
        out[rule_id] = str(item.get("result", "need_human_review"))
    return out


def _compare_expected(
    expected: dict[str, Any],
    summary: dict[str, Any],
    endogeny: dict[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    must_results = _must_rule_results(summary)
    supplementary_results = _supplementary_rule_results(summary)

    expected_overall = expected.get("overall_result")
    if expected_overall is not None:
        actual_overall = str(summary.get("overall_result", "need_human_review"))
        if actual_overall != str(expected_overall):
            mismatches.append(f"overall_result expected `{expected_overall}` but got `{actual_overall}`")

    expected_must = expected.get("must", {})
    if isinstance(expected_must, dict):
        for rule_id, expected_result in expected_must.items():
            actual_result = must_results.get(str(rule_id))
            if actual_result != str(expected_result):
                mismatches.append(
                    f"must rule `{rule_id}` expected `{expected_result}` but got `{actual_result}`"
                )

    expected_supp = expected.get("supplementary", {})
    if isinstance(expected_supp, dict):
        for rule_id, expected_result in expected_supp.items():
            actual_result = supplementary_results.get(str(rule_id))
            if actual_result != str(expected_result):
                mismatches.append(
                    f"supplementary rule `{rule_id}` expected `{expected_result}` but got `{actual_result}`"
                )

    expected_endogeny = expected.get("endogeny_result")
    if expected_endogeny is not None:
        actual_endogeny = str(endogeny.get("result", "need_human_review"))
        if actual_endogeny != str(expected_endogeny):
            mismatches.append(f"endogeny_result expected `{expected_endogeny}` but got `{actual_endogeny}`")

    return mismatches


def _render_report_markdown(report: dict[str, Any], cases_path: Path, ruleset_path: Path) -> str:
    lines: list[str] = []
    lines.append("# Golden Dataset Regression Report")
    lines.append("")
    lines.append(f"- Dataset: `{report.get('dataset_id', '')}`")
    lines.append(f"- Dataset version: `{report.get('dataset_version', '')}`")
    lines.append(f"- Cases file: `{cases_path}`")
    lines.append(f"- Ruleset: `{ruleset_path}`")
    lines.append(f"- Matched: `{report.get('matched_count', 0)}/{report.get('scenario_count', 0)}`")
    lines.append(f"- Overall status: `{'PASS' if report.get('ok', False) else 'FAIL'}`")
    lines.append("")
    lines.append("| Case ID | Scenario | Expected Overall | Actual Overall | Match | Mismatch Count |")
    lines.append("|---|---|---|---|---|---:|")

    rows = report.get("rows", [])
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("case_id", "")),
                        str(row.get("scenario", "")),
                        str(row.get("expected_overall", "")),
                        str(row.get("actual_overall", "")),
                        "yes" if bool(row.get("is_match", False)) else "no",
                        str(len(row.get("mismatches", []))),
                    ]
                )
                + " |"
            )

    lines.append("")
    lines.append("## Mismatch Details")
    lines.append("")
    mismatch_rows = [
        row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("mismatches", []), list) and row.get("mismatches")
    ] if isinstance(rows, list) else []
    if not mismatch_rows:
        lines.append("- No mismatches.")
    else:
        for row in mismatch_rows:
            lines.append(f"- `{row.get('case_id', '')}`")
            for item in row.get("mismatches", []):
                lines.append(f"  - {item}")

    return "\n".join(lines) + "\n"


def run_golden_dataset(
    output_dir: Path,
    *,
    cases_path: Path = DEFAULT_CASES_PATH,
    ruleset_path: Path = DEFAULT_RULESET_PATH,
    base_submission_path: Path = DEFAULT_BASE_SUBMISSION,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = load_case_definitions(cases_path)
    ruleset = _load_json(ruleset_path)
    base_submission = _load_json(base_submission_path)

    rows: list[dict[str, Any]] = []
    all_match = True
    cases = dataset.get("cases", [])
    if not isinstance(cases, list):
        cases = []

    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id", "")).strip()
        scenario = str(case.get("scenario", "")).strip()
        builder = SCENARIO_BUILDERS[scenario]
        expected = case.get("expected", {})
        if not isinstance(expected, dict):
            expected = {}

        submission = builder(base_submission)
        submission["submission_id"] = case_id

        summary, endogeny = run_review(submission=submission, ruleset=ruleset)
        mismatches = _compare_expected(expected=expected, summary=summary, endogeny=endogeny)
        is_match = len(mismatches) == 0
        all_match = all_match and is_match

        case_dir = output_dir / case_id
        _write_json(case_dir / "submission.structured.json", submission)
        _write_json(case_dir / "review-summary.json", summary)
        _write_text(case_dir / "review-summary.md", render_review_summary_markdown(summary))
        _write_text(case_dir / "review-summary.txt", render_review_summary_text(summary))
        _write_json(case_dir / "endogeny-result.json", endogeny)
        _write_json(
            case_dir / "assertion-result.json",
            {
                "case_id": case_id,
                "scenario": scenario,
                "expected": expected,
                "actual_overall": summary.get("overall_result", ""),
                "actual_endogeny": endogeny.get("result", ""),
                "is_match": is_match,
                "mismatches": mismatches,
            },
        )

        rows.append(
            {
                "case_id": case_id,
                "scenario": scenario,
                "expected_overall": expected.get("overall_result", ""),
                "actual_overall": summary.get("overall_result", ""),
                "actual_endogeny": endogeny.get("result", ""),
                "is_match": is_match,
                "mismatches": mismatches,
            }
        )

    report = {
        "dataset_id": dataset.get("dataset_id", ""),
        "dataset_version": dataset.get("version", ""),
        "ok": all_match,
        "scenario_count": len(rows),
        "matched_count": len([row for row in rows if bool(row.get("is_match", False))]),
        "rows": rows,
    }
    _write_json(output_dir / "golden-report.json", report)
    _write_text(output_dir / "golden-report.md", _render_report_markdown(report, cases_path, ruleset_path))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic golden regression dataset for DOAJ Reviewer.")
    parser.add_argument("--output-dir", default="artifacts/golden", help="Directory to store golden regression artifacts.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="Path to golden case definitions JSON.")
    parser.add_argument("--ruleset", default=str(DEFAULT_RULESET_PATH), help="Path to must-ruleset JSON.")
    parser.add_argument("--base-submission", default=str(DEFAULT_BASE_SUBMISSION), help="Path to base structured submission JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_golden_dataset(
        output_dir=Path(args.output_dir),
        cases_path=Path(args.cases),
        ruleset_path=Path(args.ruleset),
        base_submission_path=Path(args.base_submission),
    )
    print(f"Golden cases: {report.get('scenario_count', 0)}")
    print(f"Matched expectation: {report.get('matched_count', 0)}")
    print(f"Overall golden status: {'PASS' if report.get('ok', False) else 'FAIL'}")
    print(f"Output: {args.output_dir}")
    return 0 if bool(report.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
