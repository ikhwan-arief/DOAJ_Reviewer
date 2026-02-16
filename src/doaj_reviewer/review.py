"""Aggregate reviewer runner for the DOAJ must-ruleset."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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

MUST_RULE_HINT_BY_ID = {
    "doaj.open_access_statement.v1": "open_access_statement",
    "doaj.issn_consistency.v1": "issn_consistency",
    "doaj.publisher_identity.v1": "publisher_identity",
    "doaj.license_terms.v1": "license_terms",
    "doaj.copyright_author_rights.v1": "copyright_author_rights",
    "doaj.peer_review_policy.v1": "peer_review_policy",
    "doaj.aims_scope.v1": "aims_scope",
    "doaj.editorial_board.v1": "editorial_board",
    "doaj.instructions_for_authors.v1": "instructions_for_authors",
    "doaj.publication_fees_disclosure.v1": "publication_fees_disclosure",
    "doaj.endogeny.v1": "endogeny",
}

SUPPLEMENTARY_RULE_HINT_BY_ID = {
    "doaj.plagiarism_policy.v1": "plagiarism_policy",
    "doaj.archiving_policy.v1": "archiving_policy",
    "doaj.repository_policy.v1": "repository_policy",
}


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>").strip()


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _as_string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _text_excerpt(value: str, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _overall_result(checks: list[dict[str, Any]]) -> str:
    results = [item.get("result", "need_human_review") for item in checks]
    if any(result == "fail" for result in results):
        return "fail"
    if any(result == "need_human_review" for result in results):
        return "need_human_review"
    return "pass"


def _overall_decision_reason(overall_result: str) -> str:
    if overall_result == "fail":
        return "At least one must-rule returned fail."
    if overall_result == "need_human_review":
        return "No must-rule failed, but at least one must-rule requires human review."
    return "All must-rules passed automatically."


def _result_counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "pass": 0,
        "fail": 0,
        "need_human_review": 0,
        "not_provided": 0,
        "other": 0,
    }
    for item in checks:
        result = str(item.get("result", "other"))
        if result in counts:
            counts[result] += 1
        else:
            counts["other"] += 1
    return counts


def _source_urls_map(submission: dict[str, Any]) -> dict[str, list[str]]:
    source_urls = submission.get("source_urls", {})
    if not isinstance(source_urls, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in source_urls.items():
        hint = str(key).strip()
        if not hint:
            continue
        out[hint] = _dedupe_strings(_as_string_list(value))
    return out


def _policy_pages_map(submission: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    raw_pages = submission.get("policy_pages", [])
    if not isinstance(raw_pages, list):
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    for item in raw_pages:
        if not isinstance(item, dict):
            continue
        hint = str(item.get("rule_hint", "")).strip()
        if not hint:
            continue
        out.setdefault(hint, []).append(
            {
                "url": str(item.get("url", "")).strip(),
                "title": str(item.get("title", "")).strip(),
                "text": str(item.get("text", "")),
            }
        )
    return out


def _compact_policy_pages(pages: list[dict[str, str]], limit: int = 5) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = set()
    for page in pages:
        url = str(page.get("url", "")).strip()
        title = str(page.get("title", "")).strip()
        text = str(page.get("text", ""))
        key = (url, title)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "url": url,
                "title": title,
                "text_excerpt": _text_excerpt(text),
                "text_length": len(text.strip()),
            }
        )
        if len(out) >= limit:
            break
    return out


def _collect_crawl_notes(
    submission: dict[str, Any],
    related_urls: set[str],
    rule_hint: str,
    *,
    limit: int = 6,
) -> list[dict[str, str]]:
    evidence = submission.get("evidence", [])
    if not isinstance(evidence, list):
        return []

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in evidence:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", ""))
        if kind != "crawl_note":
            continue

        url = str(item.get("url", "")).strip()
        excerpt = _text_excerpt(str(item.get("excerpt", "")), limit=320)
        locator = str(item.get("locator_hint", "")).strip()

        include = False
        if rule_hint == "endogeny":
            include = True
        elif rule_hint and locator == f"policy-waf-blocked-{rule_hint}":
            include = True
        elif rule_hint and rule_hint in locator:
            include = True
        elif url and url in related_urls:
            include = True

        if not include:
            continue

        key = (url, locator, excerpt)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "url": url,
                "excerpt": excerpt,
                "locator_hint": locator,
            }
        )
        if len(out) >= limit:
            break
    return out


def _build_endogeny_snapshot(endogeny_report: dict[str, Any]) -> dict[str, Any]:
    metrics = endogeny_report.get("computed_metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
    units = metrics.get("units", [])
    if not isinstance(units, list):
        units = []
    limitations = endogeny_report.get("limitations", [])
    if not isinstance(limitations, list):
        limitations = []

    return {
        "publication_model": str(endogeny_report.get("publication_model", "")),
        "unit_count": len(units),
        "max_ratio_observed": metrics.get("max_ratio_observed", 0.0),
        "threshold_ratio": metrics.get("threshold_ratio", 0.25),
        "matched_article_count": len(endogeny_report.get("matched_articles", []))
        if isinstance(endogeny_report.get("matched_articles", []), list)
        else 0,
        "limitations": [str(item) for item in limitations[:5]],
    }


def _build_rule_context(
    submission: dict[str, Any],
    rule_id: str,
    evidence_urls: list[str],
    *,
    supplementary: bool,
    endogeny_report: dict[str, Any] | None,
) -> dict[str, Any]:
    hint_map = SUPPLEMENTARY_RULE_HINT_BY_ID if supplementary else MUST_RULE_HINT_BY_ID
    rule_hint = hint_map.get(rule_id, "")

    source_map = _source_urls_map(submission)
    pages_map = _policy_pages_map(submission)

    if rule_hint == "endogeny":
        related_hints = ["editorial_board", "reviewers", "latest_content", "archives"]
    elif rule_hint == "editorial_board":
        related_hints = ["editorial_board", "reviewers"]
    elif rule_hint:
        related_hints = [rule_hint]
    else:
        related_hints = []

    source_urls: list[str] = []
    pages: list[dict[str, str]] = []
    for hint in related_hints:
        source_urls.extend(source_map.get(hint, []))
        pages.extend(pages_map.get(hint, []))

    source_urls = _dedupe_strings(source_urls)
    compact_pages = _compact_policy_pages(pages)
    normalized_evidence_urls = _dedupe_strings(evidence_urls)
    related_urls = set(source_urls + normalized_evidence_urls)
    crawl_notes = _collect_crawl_notes(submission, related_urls, rule_hint)

    if source_urls or normalized_evidence_urls:
        if compact_pages:
            evidence_status = "policy_text_extracted"
        elif crawl_notes:
            evidence_status = "crawl_notes_without_policy_text"
        else:
            evidence_status = "url_provided_but_no_policy_text"
    else:
        evidence_status = "url_not_provided"

    context: dict[str, Any] = {
        "rule_hint": rule_hint,
        "source_url_count": len(source_urls),
        "source_urls": source_urls,
        "policy_page_count": len(compact_pages),
        "policy_pages": compact_pages,
        "crawl_note_count": len(crawl_notes),
        "crawl_notes": crawl_notes,
        "evidence_status": evidence_status,
    }

    if rule_id == "doaj.endogeny.v1" and endogeny_report is not None:
        context["endogeny_snapshot"] = _build_endogeny_snapshot(endogeny_report)

    return context


def _build_traceability(submission: dict[str, Any]) -> dict[str, Any]:
    source_map = _source_urls_map(submission)
    pages_map = _policy_pages_map(submission)
    hints = sorted(set(source_map.keys()) | set(pages_map.keys()))

    evidence = submission.get("evidence", [])
    crawl_note_total = 0
    if isinstance(evidence, list):
        crawl_note_total = sum(1 for item in evidence if isinstance(item, dict) and str(item.get("kind", "")) == "crawl_note")

    rows: list[dict[str, Any]] = []
    total_source_urls = 0
    total_policy_pages = 0
    for hint in hints:
        source_urls = source_map.get(hint, [])
        pages = pages_map.get(hint, [])
        note_count = len(
            _collect_crawl_notes(
                submission,
                set(source_urls),
                hint,
                limit=1000,
            )
        )

        total_source_urls += len(source_urls)
        total_policy_pages += len(pages)

        rows.append(
            {
                "rule_hint": hint,
                "submitted_url_count": len(source_urls),
                "extracted_policy_page_count": len(pages),
                "crawl_note_count": note_count,
            }
        )

    return {
        "total_source_urls_submitted": total_source_urls,
        "total_policy_pages_extracted": total_policy_pages,
        "total_crawl_notes": crawl_note_total,
        "source_url_coverage": rows,
    }


def _format_counts(counts: dict[str, Any]) -> str:
    return (
        f"pass={counts.get('pass', 0)}, "
        f"fail={counts.get('fail', 0)}, "
        f"need_human_review={counts.get('need_human_review', 0)}, "
        f"not_provided={counts.get('not_provided', 0)}, "
        f"other={counts.get('other', 0)}"
    )


def _markdown_check_table(lines: list[str], checks: list[dict[str, Any]], *, include_implemented: bool) -> None:
    if include_implemented:
        lines.append("| Rule ID | Implemented | Result | Confidence | Evidence status | Source URLs | Policy pages | Crawl notes | Notes |")
        lines.append("|---|---|---|---:|---|---:|---:|---:|---|")
    else:
        lines.append("| Rule ID | Result | Confidence | Evidence status | Source URLs | Policy pages | Crawl notes | Notes |")
        lines.append("|---|---|---:|---|---:|---:|---:|---|")

    for item in checks:
        if include_implemented:
            row = [
                _md_cell(item.get("rule_id", "")),
                _md_cell(item.get("implemented", False)),
                _md_cell(item.get("result", "")),
                _md_cell(item.get("confidence", 0)),
                _md_cell(item.get("evidence_status", "")),
                _md_cell(item.get("source_url_count", 0)),
                _md_cell(item.get("policy_page_count", 0)),
                _md_cell(item.get("crawl_note_count", 0)),
                _md_cell(item.get("notes", "")),
            ]
        else:
            row = [
                _md_cell(item.get("rule_id", "")),
                _md_cell(item.get("result", "")),
                _md_cell(item.get("confidence", 0)),
                _md_cell(item.get("evidence_status", "")),
                _md_cell(item.get("source_url_count", 0)),
                _md_cell(item.get("policy_page_count", 0)),
                _md_cell(item.get("crawl_note_count", 0)),
                _md_cell(item.get("notes", "")),
            ]
        lines.append("| " + " | ".join(row) + " |")


def _markdown_check_details(lines: list[str], checks: list[dict[str, Any]], *, include_implemented: bool) -> None:
    for item in checks:
        rule_id = str(item.get("rule_id", ""))
        lines.append(f"### `{rule_id}`")
        lines.append(f"- Rule hint: `{item.get('rule_hint', '')}`")
        if include_implemented:
            lines.append(f"- Implemented: `{item.get('implemented', False)}`")
        lines.append(f"- Result: `{item.get('result', '')}`")
        lines.append(f"- Confidence: `{item.get('confidence', 0)}`")
        lines.append(f"- Evidence status: `{item.get('evidence_status', '')}`")
        lines.append(f"- Why this result: {item.get('notes', '')}")

        source_urls = item.get("source_urls", [])
        lines.append("- Submitted URL(s):")
        if isinstance(source_urls, list) and source_urls:
            for url in source_urls:
                lines.append(f"  - `{url}`")
        else:
            lines.append("  - n/a")

        evidence_urls = item.get("evidence_urls", [])
        lines.append("- Evidence URL(s) used by evaluator:")
        if isinstance(evidence_urls, list) and evidence_urls:
            for url in evidence_urls:
                lines.append(f"  - `{url}`")
        else:
            lines.append("  - n/a")

        pages = item.get("policy_pages", [])
        lines.append("- Policy page excerpt(s):")
        if isinstance(pages, list) and pages:
            for page in pages:
                if not isinstance(page, dict):
                    continue
                title = str(page.get("title", "")).strip() or "Untitled page"
                url = str(page.get("url", "")).strip() or "n/a"
                excerpt = str(page.get("text_excerpt", "")).strip() or "(empty text)"
                length = page.get("text_length", 0)
                lines.append(f"  - {title} ({url})")
                lines.append(f"    - Text length: {length}")
                lines.append(f"    - Excerpt: {excerpt}")
        else:
            lines.append("  - n/a")

        crawl_notes = item.get("crawl_notes", [])
        lines.append("- Crawl note(s):")
        if isinstance(crawl_notes, list) and crawl_notes:
            for note in crawl_notes:
                if not isinstance(note, dict):
                    continue
                lines.append(
                    "  - "
                    + str(note.get("url", "n/a"))
                    + " | "
                    + str(note.get("locator_hint", ""))
                    + " | "
                    + str(note.get("excerpt", ""))
                )
        else:
            lines.append("  - n/a")

        snapshot = item.get("endogeny_snapshot")
        if isinstance(snapshot, dict):
            lines.append("- Endogeny snapshot:")
            lines.append(f"  - Publication model: `{snapshot.get('publication_model', '')}`")
            lines.append(f"  - Measured units: `{snapshot.get('unit_count', 0)}`")
            lines.append(f"  - Max ratio observed: `{snapshot.get('max_ratio_observed', 0.0)}`")
            lines.append(f"  - Threshold ratio: `{snapshot.get('threshold_ratio', 0.25)}`")
            lines.append(f"  - Matched articles: `{snapshot.get('matched_article_count', 0)}`")
            limitations = snapshot.get("limitations", [])
            lines.append("  - Limitations:")
            if isinstance(limitations, list) and limitations:
                for limitation in limitations:
                    lines.append(f"    - {limitation}")
            else:
                lines.append("    - None")

        lines.append("")


def render_review_summary_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# DOAJ Reviewer Summary")
    lines.append("")
    lines.append(f"- Submission ID: `{summary.get('submission_id', '')}`")
    lines.append(f"- Ruleset: `{summary.get('ruleset_id', '')}`")
    lines.append(f"- Ruleset version: `{summary.get('ruleset_version', '')}`")
    lines.append(f"- Generated at (UTC): `{summary.get('generated_at_utc', '')}`")
    lines.append(f"- Overall decision: `{summary.get('overall_result', '')}`")
    lines.append(f"- Decision rationale: {summary.get('overall_decision_reason', '')}")

    must_counts = summary.get("must_result_counts", {})
    supplementary_counts = summary.get("supplementary_result_counts", {})
    lines.append("")
    lines.append("## Decision Snapshot")
    lines.append("")
    lines.append(f"- Must checks distribution: `{_format_counts(must_counts if isinstance(must_counts, dict) else {})}`")
    lines.append(
        f"- Supplementary checks distribution: `{_format_counts(supplementary_counts if isinstance(supplementary_counts, dict) else {})}`"
    )

    traceability = summary.get("traceability", {})
    if isinstance(traceability, dict):
        lines.append("")
        lines.append("## Traceability Coverage")
        lines.append("")
        lines.append(f"- Total submitted source URLs: `{traceability.get('total_source_urls_submitted', 0)}`")
        lines.append(f"- Total extracted policy pages: `{traceability.get('total_policy_pages_extracted', 0)}`")
        lines.append(f"- Total crawl notes: `{traceability.get('total_crawl_notes', 0)}`")

        coverage_rows = traceability.get("source_url_coverage", [])
        if isinstance(coverage_rows, list) and coverage_rows:
            lines.append("")
            lines.append("| Rule hint | Submitted URLs | Extracted policy pages | Crawl notes |")
            lines.append("|---|---:|---:|---:|")
            for row in coverage_rows:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            _md_cell(row.get("rule_hint", "")),
                            _md_cell(row.get("submitted_url_count", 0)),
                            _md_cell(row.get("extracted_policy_page_count", 0)),
                            _md_cell(row.get("crawl_note_count", 0)),
                        ]
                    )
                    + " |"
                )

    lines.append("")
    lines.append("## Must Checks")
    lines.append("")
    checks = summary.get("checks", [])
    if isinstance(checks, list) and checks:
        _markdown_check_table(lines, checks, include_implemented=True)
    else:
        lines.append("No must checks available.")

    if isinstance(checks, list) and checks:
        lines.append("")
        lines.append("## Must Check Details")
        lines.append("")
        _markdown_check_details(lines, checks, include_implemented=True)

    supplementary = summary.get("supplementary_checks", [])
    if isinstance(supplementary, list) and supplementary:
        lines.append("")
        lines.append("## Supplementary Checks (Non-must)")
        lines.append("")
        _markdown_check_table(lines, supplementary, include_implemented=False)

        lines.append("")
        lines.append("## Supplementary Check Details")
        lines.append("")
        _markdown_check_details(lines, supplementary, include_implemented=False)

    return "\n".join(lines) + "\n"


def render_review_summary_text(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("DOAJ Reviewer Summary")
    lines.append("=" * 21)
    lines.append(f"Submission ID       : {summary.get('submission_id', '')}")
    lines.append(f"Ruleset             : {summary.get('ruleset_id', '')}")
    lines.append(f"Ruleset version     : {summary.get('ruleset_version', '')}")
    lines.append(f"Generated at (UTC)  : {summary.get('generated_at_utc', '')}")
    lines.append(f"Overall             : {summary.get('overall_result', '')}")
    lines.append(f"Decision rationale  : {summary.get('overall_decision_reason', '')}")

    lines.append("")
    lines.append("Decision Snapshot")
    lines.append("-" * 17)
    lines.append("Must checks         : " + _format_counts(summary.get("must_result_counts", {})))
    lines.append("Supplementary checks: " + _format_counts(summary.get("supplementary_result_counts", {})))

    traceability = summary.get("traceability", {})
    if isinstance(traceability, dict):
        lines.append("")
        lines.append("Traceability Coverage")
        lines.append("-" * 21)
        lines.append(f"Total submitted source URLs : {traceability.get('total_source_urls_submitted', 0)}")
        lines.append(f"Total extracted policy pages: {traceability.get('total_policy_pages_extracted', 0)}")
        lines.append(f"Total crawl notes           : {traceability.get('total_crawl_notes', 0)}")
        coverage_rows = traceability.get("source_url_coverage", [])
        if isinstance(coverage_rows, list) and coverage_rows:
            lines.append("Per-rule coverage:")
            for row in coverage_rows:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    "  - "
                    + f"{row.get('rule_hint', '')}: "
                    + f"submitted={row.get('submitted_url_count', 0)}, "
                    + f"pages={row.get('extracted_policy_page_count', 0)}, "
                    + f"crawl_notes={row.get('crawl_note_count', 0)}"
                )

    lines.append("")
    lines.append("Must Checks")
    lines.append("-" * 10)
    checks = summary.get("checks", [])
    if isinstance(checks, list):
        for idx, check in enumerate(checks, start=1):
            lines.append(f"{idx}. Rule ID        : {check.get('rule_id', '')}")
            lines.append(f"   Rule hint       : {check.get('rule_hint', '')}")
            lines.append(f"   Implemented     : {check.get('implemented', False)}")
            lines.append(f"   Result          : {check.get('result', '')}")
            lines.append(f"   Confidence      : {check.get('confidence', 0)}")
            lines.append(f"   Evidence status : {check.get('evidence_status', '')}")
            lines.append(f"   Notes           : {check.get('notes', '')}")

            source_urls = check.get("source_urls", [])
            lines.append("   Submitted URLs  :")
            if isinstance(source_urls, list) and source_urls:
                for url in source_urls:
                    lines.append(f"     - {url}")
            else:
                lines.append("     - n/a")

            evidence_urls = check.get("evidence_urls", [])
            lines.append("   Evidence URLs   :")
            if isinstance(evidence_urls, list) and evidence_urls:
                for url in evidence_urls:
                    lines.append(f"     - {url}")
            else:
                lines.append("     - n/a")

            pages = check.get("policy_pages", [])
            lines.append("   Policy pages    :")
            if isinstance(pages, list) and pages:
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    lines.append(
                        f"     - {page.get('title', 'Untitled')} ({page.get('url', 'n/a')}) | "
                        f"len={page.get('text_length', 0)}"
                    )
                    lines.append(f"       excerpt: {page.get('text_excerpt', '')}")
            else:
                lines.append("     - n/a")

            crawl_notes = check.get("crawl_notes", [])
            lines.append("   Crawl notes     :")
            if isinstance(crawl_notes, list) and crawl_notes:
                for note in crawl_notes:
                    if not isinstance(note, dict):
                        continue
                    lines.append(
                        "     - "
                        + str(note.get("url", "n/a"))
                        + " | "
                        + str(note.get("locator_hint", ""))
                        + " | "
                        + str(note.get("excerpt", ""))
                    )
            else:
                lines.append("     - n/a")

            snapshot = check.get("endogeny_snapshot")
            if isinstance(snapshot, dict):
                lines.append("   Endogeny snapshot:")
                lines.append(f"     - publication_model   : {snapshot.get('publication_model', '')}")
                lines.append(f"     - measured_units      : {snapshot.get('unit_count', 0)}")
                lines.append(f"     - max_ratio_observed  : {snapshot.get('max_ratio_observed', 0.0)}")
                lines.append(f"     - threshold_ratio     : {snapshot.get('threshold_ratio', 0.25)}")
                lines.append(f"     - matched_articles    : {snapshot.get('matched_article_count', 0)}")
                limitations = snapshot.get("limitations", [])
                lines.append("     - limitations         :")
                if isinstance(limitations, list) and limitations:
                    for limitation in limitations:
                        lines.append(f"       - {limitation}")
                else:
                    lines.append("       - None")

            lines.append("")

    supplementary = summary.get("supplementary_checks", [])
    if isinstance(supplementary, list) and supplementary:
        lines.append("Supplementary Checks (Non-must)")
        lines.append("-" * 30)
        for idx, item in enumerate(supplementary, start=1):
            lines.append(f"{idx}. Rule ID        : {item.get('rule_id', '')}")
            lines.append(f"   Rule hint       : {item.get('rule_hint', '')}")
            lines.append(f"   Result          : {item.get('result', '')}")
            lines.append(f"   Confidence      : {item.get('confidence', 0)}")
            lines.append(f"   Evidence status : {item.get('evidence_status', '')}")
            lines.append(f"   Notes           : {item.get('notes', '')}")

            source_urls = item.get("source_urls", [])
            lines.append("   Submitted URLs  :")
            if isinstance(source_urls, list) and source_urls:
                for url in source_urls:
                    lines.append(f"     - {url}")
            else:
                lines.append("     - n/a")

            evidence_urls = item.get("evidence_urls", [])
            lines.append("   Evidence URLs   :")
            if isinstance(evidence_urls, list) and evidence_urls:
                for url in evidence_urls:
                    lines.append(f"     - {url}")
            else:
                lines.append("     - n/a")

            pages = item.get("policy_pages", [])
            lines.append("   Policy pages    :")
            if isinstance(pages, list) and pages:
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    lines.append(
                        f"     - {page.get('title', 'Untitled')} ({page.get('url', 'n/a')}) | "
                        f"len={page.get('text_length', 0)}"
                    )
                    lines.append(f"       excerpt: {page.get('text_excerpt', '')}")
            else:
                lines.append("     - n/a")

            crawl_notes = item.get("crawl_notes", [])
            lines.append("   Crawl notes     :")
            if isinstance(crawl_notes, list) and crawl_notes:
                for note in crawl_notes:
                    if not isinstance(note, dict):
                        continue
                    lines.append(
                        "     - "
                        + str(note.get("url", "n/a"))
                        + " | "
                        + str(note.get("locator_hint", ""))
                        + " | "
                        + str(note.get("excerpt", ""))
                    )
            else:
                lines.append("     - n/a")

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
            evidence_urls = []
            for item in endogeny_report.get("evidence", []):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url", "")).strip()
                if url:
                    evidence_urls.append(url)
            checks_out.append(
                {
                    "rule_id": rule_id,
                    "implemented": True,
                    "result": endogeny_report.get("result", "need_human_review"),
                    "confidence": endogeny_report.get("confidence", 0.0),
                    "notes": endogeny_report.get("explanation_en", ""),
                    "evidence_urls": _dedupe_strings(evidence_urls),
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
                    "evidence_urls": _dedupe_strings(_as_string_list(outcome.get("evidence_urls", []))),
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
                    "evidence_urls": [],
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
                "evidence_urls": [],
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
                "evidence_urls": _dedupe_strings(_as_string_list(outcome.get("evidence_urls", []))),
            }
        )

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
                "all_units_within_threshold": False,
            },
            "matched_articles": [],
            "evidence": [],
            "limitations": [
                "Endogeny evaluator did not run.",
            ],
            "version": "1.0.0",
            "crawl_timestamp_utc": submission.get("crawl_timestamp_utc", ""),
            "publication_model": submission.get("publication_model", "unknown"),
        }

    for item in checks_out:
        context = _build_rule_context(
            submission=submission,
            rule_id=str(item.get("rule_id", "")),
            evidence_urls=_as_string_list(item.get("evidence_urls", [])),
            supplementary=False,
            endogeny_report=endogeny_report,
        )
        item.update(context)

    for item in supplementary_checks:
        context = _build_rule_context(
            submission=submission,
            rule_id=str(item.get("rule_id", "")),
            evidence_urls=_as_string_list(item.get("evidence_urls", [])),
            supplementary=True,
            endogeny_report=None,
        )
        item.update(context)

    overall = _overall_result(checks_out)
    must_counts = _result_counts(checks_out)
    supplementary_counts = _result_counts(supplementary_checks)

    summary = {
        "submission_id": submission.get("submission_id", ""),
        "ruleset_id": ruleset.get("ruleset_id", ""),
        "ruleset_version": ruleset.get("version", ""),
        "generated_at_utc": _now_iso_utc(),
        "overall_result": overall,
        "overall_decision_reason": _overall_decision_reason(overall),
        "must_result_counts": must_counts,
        "supplementary_result_counts": supplementary_counts,
        "traceability": _build_traceability(submission),
        "checks": checks_out,
        "supplementary_checks": supplementary_checks,
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
