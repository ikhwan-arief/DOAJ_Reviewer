"""Markdown reporting for reviewer outputs."""

from __future__ import annotations

from typing import Any


def _safe(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def render_endogeny_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Endogeny Audit Report")
    lines.append("")
    lines.append(f"- Rule ID: `{_safe(result.get('rule_id'))}`")
    lines.append(f"- Decision: `{_safe(result.get('result'))}`")
    lines.append(f"- Confidence: `{_safe(result.get('confidence'))}`")
    lines.append(f"- Crawl timestamp (UTC): `{_safe(result.get('crawl_timestamp_utc'))}`")
    lines.append("")
    lines.append("## Summary (English)")
    lines.append(_safe(result.get("explanation_en")))
    lines.append("")
    lines.append("## Metrics")
    lines.append("| Unit | Window | Research articles | Matched articles | Ratio | Threshold |")
    lines.append("|---|---|---:|---:|---:|---:|")

    metrics = result.get("computed_metrics", {}).get("units", [])
    if metrics:
        for unit in metrics:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _safe(unit.get("label")),
                        _safe(unit.get("window_type")),
                        _safe(unit.get("research_article_count")),
                        _safe(unit.get("matched_article_count")),
                        _safe(unit.get("ratio")),
                        "0.25",
                    ]
                )
                + " |"
            )
    else:
        lines.append("| n/a | n/a | 0 | 0 | 0 | 0.25 |")

    lines.append("")
    lines.append("## Matched Articles")
    lines.append("| Unit | Article title | Article URL | Matched author | Matched role | Matched person | Method | Score |")
    lines.append("|---|---|---|---|---|---|---|---:|")
    matched = result.get("matched_articles", [])
    if matched:
        for item in matched:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _safe(item.get("unit_label")),
                        _safe(item.get("article_title")),
                        _safe(item.get("article_url")),
                        _safe(item.get("matched_author")),
                        _safe(item.get("matched_role")),
                        _safe(item.get("matched_person_name")),
                        _safe(item.get("matching_method")),
                        _safe(item.get("match_score")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0 |")

    lines.append("")
    lines.append("## Sources and Evidence")
    lines.append("| Kind | URL | Excerpt | Locator hint |")
    lines.append("|---|---|---|---|")
    evidence = result.get("evidence", [])
    if evidence:
        for item in evidence:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _safe(item.get("kind")),
                        _safe(item.get("url")),
                        _safe(item.get("excerpt")),
                        _safe(item.get("locator_hint")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| n/a | n/a | n/a | n/a |")

    limitations = result.get("limitations", [])
    lines.append("")
    lines.append("## Missing Data / Limitations")
    if limitations:
        for limitation in limitations:
            lines.append(f"- {_safe(limitation)}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"
