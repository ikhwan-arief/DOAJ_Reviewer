"""Batch utilities for spreadsheet-driven submissions."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from .intake import build_structured_submission_from_raw
from .review import render_review_summary_markdown, render_review_summary_text, run_review
from .reporting import render_endogeny_markdown


LIST_FIELDS = [
    "open_access_statement",
    "issn_consistency",
    "publisher_identity",
    "license_terms",
    "copyright_author_rights",
    "peer_review_policy",
    "plagiarism_policy",
    "aims_scope",
    "editorial_board",
    "reviewers",
    "latest_content",
    "instructions_for_authors",
    "publication_fees_disclosure",
    "archiving_policy",
    "repository_policy",
    "archives",
]

REQUIRED_COLUMNS = [
    "submission_id",
    "journal_homepage_url",
    "publication_model",
    "open_access_statement_urls",
    "issn_consistency_urls",
    "publisher_identity_urls",
    "license_terms_urls",
    "copyright_author_rights_urls",
    "peer_review_policy_urls",
    "aims_scope_urls",
    "editorial_board_urls",
    "instructions_for_authors_urls",
    "publication_fees_disclosure_urls",
    "latest_content_urls",
]

RESULT_RULE_COLUMNS = [
    "doaj.open_access_statement.v1",
    "doaj.issn_consistency.v1",
    "doaj.publisher_identity.v1",
    "doaj.license_terms.v1",
    "doaj.copyright_author_rights.v1",
    "doaj.peer_review_policy.v1",
    "doaj.aims_scope.v1",
    "doaj.editorial_board.v1",
    "doaj.instructions_for_authors.v1",
    "doaj.publication_fees_disclosure.v1",
    "doaj.endogeny.v1",
]


def _split_urls(cell: str, list_sep: str) -> list[str]:
    if not cell:
        return []
    out: list[str] = []
    seen = set()
    for raw in cell.split(list_sep):
        url = raw.strip()
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _row_to_raw_submission(row: dict[str, str], list_sep: str) -> dict[str, Any]:
    source_urls = {
        "open_access_statement": _split_urls(row.get("open_access_statement_urls", ""), list_sep),
        "issn_consistency": _split_urls(row.get("issn_consistency_urls", ""), list_sep),
        "publisher_identity": _split_urls(row.get("publisher_identity_urls", ""), list_sep),
        "license_terms": _split_urls(row.get("license_terms_urls", ""), list_sep),
        "copyright_author_rights": _split_urls(row.get("copyright_author_rights_urls", ""), list_sep),
        "peer_review_policy": _split_urls(row.get("peer_review_policy_urls", ""), list_sep),
        "plagiarism_policy": _split_urls(row.get("plagiarism_policy_urls", ""), list_sep),
        "aims_scope": _split_urls(row.get("aims_scope_urls", ""), list_sep),
        "editorial_board": _split_urls(row.get("editorial_board_urls", ""), list_sep),
        "reviewers": _split_urls(row.get("reviewers_urls", ""), list_sep),
        "latest_content": _split_urls(row.get("latest_content_urls", ""), list_sep),
        "instructions_for_authors": _split_urls(row.get("instructions_for_authors_urls", ""), list_sep),
        "publication_fees_disclosure": _split_urls(row.get("publication_fees_disclosure_urls", ""), list_sep),
        "archiving_policy": _split_urls(row.get("archiving_policy_urls", ""), list_sep),
        "repository_policy": _split_urls(row.get("repository_policy_urls", ""), list_sep),
        "archives": _split_urls(row.get("archives_urls", ""), list_sep),
    }
    return {
        "submission_id": (row.get("submission_id", "") or "").strip(),
        "journal_homepage_url": (row.get("journal_homepage_url", "") or "").strip(),
        "publication_model": (row.get("publication_model", "issue_based") or "issue_based").strip(),
        "source_urls": source_urls,
    }


def _validate_raw_submission(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not raw.get("submission_id"):
        errors.append("missing submission_id")
    if not raw.get("journal_homepage_url"):
        errors.append("missing journal_homepage_url")
    if raw.get("publication_model") not in {"issue_based", "continuous"}:
        errors.append("publication_model must be issue_based or continuous")
    source_urls = raw.get("source_urls", {})
    required_hints = [
        "open_access_statement",
        "issn_consistency",
        "publisher_identity",
        "license_terms",
        "copyright_author_rights",
        "peer_review_policy",
        "aims_scope",
        "editorial_board",
        "instructions_for_authors",
        "publication_fees_disclosure",
        "latest_content",
    ]
    for hint in required_hints:
        if not source_urls.get(hint):
            errors.append(f"{hint}_urls is required")
    return errors


def _load_ruleset(path: Path) -> dict[str, Any]:
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


def _write_overview_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["submission_id", "overall_result"] + RESULT_RULE_COLUMNS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_batch(
    input_csv: Path,
    output_dir: Path,
    ruleset_path: Path,
    list_sep: str = "|",
    js_mode: str = "auto",
    convert_only: bool = False,
) -> int:
    ruleset = {} if convert_only else _load_ruleset(ruleset_path)
    results_overview: list[dict[str, str]] = []

    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Input CSV has no header.")
        missing_cols = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
        if missing_cols:
            raise ValueError(f"Missing required columns: {', '.join(missing_cols)}")

        for idx, row in enumerate(reader, start=2):
            raw = _row_to_raw_submission(row, list_sep=list_sep)
            errors = _validate_raw_submission(raw)
            if errors:
                raise ValueError(f"Row {idx} ({raw.get('submission_id','')}): " + "; ".join(errors))

            submission_id = str(raw["submission_id"])
            base = output_dir / submission_id
            raw_path = base / "submission.raw.json"
            structured_path = base / "submission.structured.json"
            summary_json_path = base / "review-summary.json"
            summary_md_path = base / "review-summary.md"
            summary_txt_path = base / "review-summary.txt"
            endogeny_json_path = base / "endogeny-result.json"
            endogeny_md_path = base / "endogeny-report.md"

            _write_json(raw_path, raw)
            if convert_only:
                overview_row = {
                    "submission_id": submission_id,
                    "overall_result": "not_run",
                }
                for rule_id in RESULT_RULE_COLUMNS:
                    overview_row[rule_id] = ""
                results_overview.append(overview_row)
                continue

            structured = build_structured_submission_from_raw(raw, js_mode=js_mode)
            _write_json(structured_path, structured)

            summary, endogeny = run_review(submission=structured, ruleset=ruleset)
            _write_json(summary_json_path, summary)
            _write_text(summary_md_path, render_review_summary_markdown(summary))
            _write_text(summary_txt_path, render_review_summary_text(summary))
            _write_json(endogeny_json_path, endogeny)
            _write_text(endogeny_md_path, render_endogeny_markdown(endogeny))

            by_rule = {item["rule_id"]: item["result"] for item in summary.get("checks", [])}
            overview_row = {
                "submission_id": submission_id,
                "overall_result": str(summary.get("overall_result", "")),
            }
            for rule_id in RESULT_RULE_COLUMNS:
                overview_row[rule_id] = str(by_rule.get(rule_id, ""))
            results_overview.append(overview_row)

    _write_overview_csv(output_dir / "overview.csv", results_overview)
    return len(results_overview)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DOAJ Reviewer batch from spreadsheet CSV.")
    parser.add_argument("--input-csv", required=True, help="Path to CSV exported from spreadsheet.")
    parser.add_argument("--output-dir", required=True, help="Directory for per-submission outputs.")
    parser.add_argument(
        "--ruleset",
        default="specs/reviewer/rules/ruleset.must.v1.json",
        help="Path to ruleset JSON.",
    )
    parser.add_argument(
        "--list-sep",
        default="|",
        help="Separator used inside URL list cells. Default: |",
    )
    parser.add_argument(
        "--js-mode",
        choices=["off", "auto", "on"],
        default="auto",
        help="JS rendering mode for intake fetcher.",
    )
    parser.add_argument(
        "--convert-only",
        action="store_true",
        help="Only validate + convert rows to raw JSON; skip intake/review network execution.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    count = run_batch(
        input_csv=Path(args.input_csv),
        output_dir=Path(args.output_dir),
        ruleset_path=Path(args.ruleset),
        list_sep=args.list_sep,
        js_mode=args.js_mode,
        convert_only=args.convert_only,
    )
    print(f"Processed submissions: {count}")
    print(f"Output directory: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
