"""Aggregate reviewer runner for the DOAJ must-ruleset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .basic_rules import (
    evaluate_aims_scope,
    evaluate_archiving_policy,
    evaluate_copyright_author_rights,
    evaluate_editorial_board,
    evaluate_issn_consistency,
    evaluate_instructions_for_authors,
    evaluate_license_terms,
    evaluate_open_access_statement,
    evaluate_peer_review_policy,
    evaluate_plagiarism_policy,
    evaluate_publisher_identity,
    evaluate_publication_fees_disclosure,
    evaluate_repository_policy,
)
from .endogeny import evaluate_endogeny
from .reporting import render_endogeny_markdown


DEFAULT_RULESET_PATH = "specs/reviewer/rules/ruleset.must.v1.json"


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


def _overall_result(checks: list[dict[str, Any]]) -> str:
    results = [item.get("result", "need_human_review") for item in checks]
    if any(result == "fail" for result in results):
        return "fail"
    if any(result == "need_human_review" for result in results):
        return "need_human_review"
    return "pass"


def render_review_summary_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# DOAJ Reviewer Summary")
    lines.append("")
    lines.append(f"- Submission ID: `{summary.get('submission_id', '')}`")
    lines.append(f"- Ruleset: `{summary.get('ruleset_id', '')}`")
    lines.append(f"- Overall decision: `{summary.get('overall_result', '')}`")
    lines.append("")
    lines.append("| Rule ID | Implemented | Result | Confidence | Evidence URLs | Notes |")
    lines.append("|---|---|---|---:|---|---|")
    for check in summary.get("checks", []):
        evidence_urls = check.get("evidence_urls", [])
        if isinstance(evidence_urls, list):
            evidence_text = "<br>".join(str(url) for url in evidence_urls[:3])
        else:
            evidence_text = ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(check.get("rule_id", "")),
                    str(check.get("implemented", False)),
                    str(check.get("result", "")),
                    str(check.get("confidence", 0)),
                    evidence_text,
                    str(check.get("notes", "")),
                ]
            )
            + " |"
        )

    supplementary = summary.get("supplementary_checks", [])
    if supplementary:
        lines.append("")
        lines.append("## Supplementary Checks (Non-must)")
        lines.append("")
        lines.append("| Rule ID | Result | Confidence | Evidence URLs | Notes |")
        lines.append("|---|---|---:|---|---|")
        for item in supplementary:
            evidence_urls = item.get("evidence_urls", [])
            evidence_text = "<br>".join(str(url) for url in evidence_urls[:3]) if isinstance(evidence_urls, list) else ""
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item.get("rule_id", "")),
                        str(item.get("result", "")),
                        str(item.get("confidence", 0)),
                        evidence_text,
                        str(item.get("notes", "")),
                    ]
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def render_review_summary_text(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("DOAJ Reviewer Summary")
    lines.append("=" * 21)
    lines.append(f"Submission ID : {summary.get('submission_id', '')}")
    lines.append(f"Ruleset       : {summary.get('ruleset_id', '')}")
    lines.append(f"Overall       : {summary.get('overall_result', '')}")
    lines.append("")
    lines.append("Must Checks")
    lines.append("-" * 10)
    for idx, check in enumerate(summary.get("checks", []), start=1):
        lines.append(f"{idx}. Rule ID    : {check.get('rule_id', '')}")
        lines.append(f"   Result     : {check.get('result', '')}")
        lines.append(f"   Confidence : {check.get('confidence', 0)}")
        lines.append(f"   Notes      : {check.get('notes', '')}")
        evidence_urls = check.get("evidence_urls", [])
        if isinstance(evidence_urls, list) and evidence_urls:
            lines.append("   Evidence   :")
            for url in evidence_urls[:5]:
                lines.append(f"     - {url}")
        lines.append("")

    supplementary = summary.get("supplementary_checks", [])
    if supplementary:
        lines.append("Supplementary Checks (Non-must)")
        lines.append("-" * 30)
        for idx, item in enumerate(supplementary, start=1):
            lines.append(f"{idx}. Rule ID    : {item.get('rule_id', '')}")
            lines.append(f"   Result     : {item.get('result', '')}")
            lines.append(f"   Confidence : {item.get('confidence', 0)}")
            lines.append(f"   Notes      : {item.get('notes', '')}")
            evidence_urls = item.get("evidence_urls", [])
            if isinstance(evidence_urls, list) and evidence_urls:
                lines.append("   Evidence   :")
                for url in evidence_urls[:5]:
                    lines.append(f"     - {url}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_review(submission: dict[str, Any], ruleset: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    checks_out: list[dict[str, Any]] = []
    supplementary_checks: list[dict[str, Any]] = []
    endogeny_report: dict[str, Any] | None = None
    rule_evaluators = {
        "doaj.open_access_statement.v1": evaluate_open_access_statement,
        "doaj.aims_scope.v1": evaluate_aims_scope,
        "doaj.editorial_board.v1": evaluate_editorial_board,
        "doaj.instructions_for_authors.v1": evaluate_instructions_for_authors,
        "doaj.peer_review_policy.v1": evaluate_peer_review_policy,
        "doaj.license_terms.v1": evaluate_license_terms,
        "doaj.copyright_author_rights.v1": evaluate_copyright_author_rights,
        "doaj.publication_fees_disclosure.v1": evaluate_publication_fees_disclosure,
        "doaj.publisher_identity.v1": evaluate_publisher_identity,
        "doaj.issn_consistency.v1": evaluate_issn_consistency,
    }
    supplementary_evaluators = [
        evaluate_plagiarism_policy,
        evaluate_archiving_policy,
        evaluate_repository_policy,
    ]

    for check in ruleset.get("checks", []):
        rule_id = str(check.get("rule_id", ""))
        implemented = bool(check.get("implemented", False))
        if rule_id == "doaj.endogeny.v1":
            endogeny_report = evaluate_endogeny(submission)
            checks_out.append(
                {
                    "rule_id": rule_id,
                    "implemented": True,
                    "result": endogeny_report["result"],
                    "confidence": endogeny_report["confidence"],
                    "notes": endogeny_report["explanation_en"],
                }
            )
            continue

        if rule_id in rule_evaluators:
            outcome = rule_evaluators[rule_id](submission)
            checks_out.append(
                {
                    "rule_id": rule_id,
                    "implemented": True,
                    "result": outcome.get("result", "need_human_review"),
                    "confidence": outcome.get("confidence", 0.0),
                    "notes": outcome.get("notes", ""),
                    "evidence_urls": outcome.get("evidence_urls", []),
                }
            )
            continue

        if not implemented:
            checks_out.append(
                {
                    "rule_id": rule_id,
                    "implemented": False,
                    "result": "need_human_review",
                    "confidence": 0.0,
                    "notes": "Rule evaluator is not implemented yet.",
                }
            )
            continue

        checks_out.append(
            {
                "rule_id": rule_id,
                "implemented": True,
                "result": "need_human_review",
                "confidence": 0.0,
                "notes": "Rule is marked implemented but no evaluator binding exists.",
            }
        )

    for evaluator in supplementary_evaluators:
        outcome = evaluator(submission)
        supplementary_checks.append(
            {
                "rule_id": outcome.get("rule_id", ""),
                "result": outcome.get("result", "need_human_review"),
                "confidence": outcome.get("confidence", 0.0),
                "notes": outcome.get("notes", ""),
                "evidence_urls": outcome.get("evidence_urls", []),
            }
        )

    summary = {
        "submission_id": submission.get("submission_id", ""),
        "ruleset_id": ruleset.get("ruleset_id", ""),
        "ruleset_version": ruleset.get("version", ""),
        "overall_result": _overall_result(checks_out),
        "checks": checks_out,
        "supplementary_checks": supplementary_checks,
    }
    if endogeny_report is None:
        endogeny_report = {
            "rule_id": "doaj.endogeny.v1",
            "result": "need_human_review",
            "confidence": 0.0,
            "explanation_en": "Endogeny evaluator did not run.",
            "computed_metrics": {
                "units": [],
                "max_ratio_observed": 0.0,
                "threshold_ratio": 0.25,
                "all_units_within_threshold": False
            },
            "matched_articles": [],
            "evidence": [],
            "limitations": [
                "Endogeny evaluator did not run."
            ],
            "version": "1.0.0",
            "crawl_timestamp_utc": submission.get("crawl_timestamp_utc", ""),
            "publication_model": submission.get("publication_model", "unknown")
        }
    return summary, endogeny_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DOAJ reviewer ruleset.")
    parser.add_argument("--submission", required=True, help="Path to structured submission JSON.")
    parser.add_argument("--ruleset", default=DEFAULT_RULESET_PATH, help="Path to must-ruleset JSON.")
    parser.add_argument("--summary-json", default="artifacts/review-summary.json", help="Path to output summary JSON.")
    parser.add_argument("--summary-md", default="artifacts/review-summary.md", help="Path to output summary Markdown.")
    parser.add_argument("--summary-txt", default="artifacts/review-summary.txt", help="Path to output summary text.")
    parser.add_argument("--endogeny-json", default="artifacts/endogeny-result.json", help="Path to output endogeny JSON.")
    parser.add_argument("--endogeny-md", default="artifacts/endogeny-report.md", help="Path to output endogeny Markdown.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    submission = _load_json(Path(args.submission))
    ruleset = _load_json(Path(args.ruleset))
    summary, endogeny = run_review(submission=submission, ruleset=ruleset)

    _write_json(Path(args.summary_json), summary)
    _write_text(Path(args.summary_md), render_review_summary_markdown(summary))
    _write_text(Path(args.summary_txt), render_review_summary_text(summary))
    _write_json(Path(args.endogeny_json), endogeny)
    _write_text(Path(args.endogeny_md), render_endogeny_markdown(endogeny))

    print(f"Submission: {summary.get('submission_id', '')}")
    print(f"Overall decision: {summary.get('overall_result', '')}")
    print(f"Summary JSON: {args.summary_json}")
    print(f"Summary MD: {args.summary_md}")
    print(f"Summary TXT: {args.summary_txt}")
    print(f"Endogeny JSON: {args.endogeny_json}")
    print(f"Endogeny MD: {args.endogeny_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
