"""Endogeny evaluator logic for DOAJ reviewer."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any

RULE_ID = "doaj.endogeny.v1"
RULE_VERSION = "1.0.0"
THRESHOLD = 0.25
FUZZY_THRESHOLD = 0.94

_TITLE_RE = re.compile(r"\b(dr|prof|professor|mr|ms|mrs)\.?\b", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = _TITLE_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def initials_plus_family_key(normalized_name: str) -> str:
    parts = normalized_name.split()
    if not parts:
        return ""
    family = parts[-1]
    initials = "".join(part[0] for part in parts[:-1] if part)
    return f"{initials}|{family}"


def _build_people_index(role_people: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    people: list[dict[str, Any]] = []
    by_exact: dict[str, list[dict[str, Any]]] = {}
    by_initials: dict[str, list[dict[str, Any]]] = {}

    for person in role_people:
        normalized = normalize_name(person.get("name", ""))
        if not normalized:
            continue
        entry = {
            "name": person.get("name", ""),
            "role": person.get("role", ""),
            "source_url": person.get("source_url", ""),
            "normalized_name": normalized,
            "initials_key": initials_plus_family_key(normalized),
        }
        people.append(entry)
        by_exact.setdefault(normalized, []).append(entry)
        if entry["initials_key"]:
            by_initials.setdefault(entry["initials_key"], []).append(entry)
    return people, by_exact, by_initials


def _match_author(
    author_name: str,
    people: list[dict[str, Any]],
    by_exact: dict[str, list[dict[str, Any]]],
    by_initials: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    normalized_author = normalize_name(author_name)
    if not normalized_author:
        return None

    exact_matches = by_exact.get(normalized_author, [])
    if exact_matches:
        person = exact_matches[0]
        return {
            "author": author_name,
            "person": person,
            "matching_method": "exact_normalized_name",
            "match_score": 1.0,
        }

    key = initials_plus_family_key(normalized_author)
    initials_matches = by_initials.get(key, []) if key else []
    if initials_matches:
        person = initials_matches[0]
        return {
            "author": author_name,
            "person": person,
            "matching_method": "initials_plus_family_name",
            "match_score": 0.97,
        }

    best: dict[str, Any] | None = None
    for person in people:
        score = SequenceMatcher(None, normalized_author, person["normalized_name"]).ratio()
        if score < FUZZY_THRESHOLD:
            continue
        if best is None or score > best["match_score"]:
            best = {
                "author": author_name,
                "person": person,
                "matching_method": "fuzzy_name",
                "match_score": round(float(score), 4),
            }
    return best


def _sanitize_evidence(raw: Any) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return evidence
    for item in raw:
        if not isinstance(item, dict):
            continue
        excerpt = str(item.get("excerpt", ""))[:300]
        entry = {
            "kind": str(item.get("kind", "crawl_note")),
            "url": str(item.get("url", "")),
            "excerpt": excerpt,
            "locator_hint": str(item.get("locator_hint", "")),
        }
        if entry["url"]:
            evidence.append(entry)
    return evidence


def _classify_decision(
    publication_model: str,
    measured_units: list[dict[str, Any]],
    max_ratio_observed: float,
) -> tuple[str, list[str]]:
    limitations: list[str] = []
    sufficient_evidence = True

    if not measured_units:
        sufficient_evidence = False
        limitations.append("No measurable unit was found for endogeny computation.")

    if publication_model == "issue_based":
        if len(measured_units) < 2:
            sufficient_evidence = False
            limitations.append("Latest two issues are not fully available.")
    elif publication_model == "continuous":
        article_total = sum(unit["research_article_count"] for unit in measured_units)
        if article_total < 5:
            sufficient_evidence = False
            limitations.append("Continuous model has fewer than 5 research articles in the last calendar year.")

    for unit in measured_units:
        if unit["research_article_count"] == 0:
            sufficient_evidence = False
            limitations.append(f"Unit '{unit['label']}' has zero research articles.")

    if max_ratio_observed > THRESHOLD:
        return "fail", limitations
    if sufficient_evidence:
        return "pass", limitations
    return "need_human_review", limitations


def _confidence_score(result: str, matched_articles: list[dict[str, Any]], limitations: list[str]) -> float:
    base = 0.9 if result in {"pass", "fail"} else 0.66
    fuzzy_count = sum(1 for item in matched_articles if item["matching_method"] == "fuzzy_name")
    initials_count = sum(1 for item in matched_articles if item["matching_method"] == "initials_plus_family_name")
    base -= min(0.2, 0.05 * fuzzy_count)
    base -= min(0.1, 0.02 * initials_count)
    base -= min(0.35, 0.08 * len(limitations))
    return round(max(0.1, min(0.99, base)), 2)


def _explanation(result: str, unit_count: int, max_ratio: float, limitations: list[str]) -> str:
    ratio_pct = round(max_ratio * 100, 2)
    if result == "fail":
        return (
            f"Endogeny exceeds the 25% threshold. "
            f"Max observed ratio is {ratio_pct}% across {unit_count} measured unit(s)."
        )
    if result == "pass":
        return (
            f"Endogeny is within the 25% threshold. "
            f"Max observed ratio is {ratio_pct}% across {unit_count} measured unit(s)."
        )
    reason = limitations[0] if limitations else "Evidence is incomplete or ambiguous."
    return (
        f"Endogeny cannot be decided with high confidence. "
        f"Max observed ratio is {ratio_pct}% across {unit_count} measured unit(s). "
        f"Primary limitation: {reason}"
    )


def evaluate_endogeny(submission: dict[str, Any]) -> dict[str, Any]:
    publication_model = submission.get("publication_model", "unknown")
    units = submission.get("units", [])
    role_people = submission.get("role_people", [])

    people, by_exact, by_initials = _build_people_index(role_people)
    matched_articles: list[dict[str, Any]] = []
    metrics_units: list[dict[str, Any]] = []

    for unit in units:
        label = str(unit.get("label", "Unknown unit"))
        window_type = str(unit.get("window_type", "issue"))
        research_articles = unit.get("research_articles", [])
        denominator = len(research_articles)
        numerator = 0

        for article in research_articles:
            article_title = str(article.get("title", "Untitled article"))
            article_url = str(article.get("url", ""))
            authors = article.get("authors", [])

            best_match: dict[str, Any] | None = None
            for author_name in authors:
                maybe_match = _match_author(str(author_name), people, by_exact, by_initials)
                if maybe_match is None:
                    continue
                if best_match is None or maybe_match["match_score"] > best_match["match_score"]:
                    best_match = maybe_match

            if best_match is not None:
                numerator += 1
                matched_articles.append(
                    {
                        "unit_label": label,
                        "article_title": article_title,
                        "article_url": article_url,
                        "matched_author": best_match["author"],
                        "matched_role": best_match["person"]["role"],
                        "matched_person_name": best_match["person"]["name"],
                        "matching_method": best_match["matching_method"],
                        "match_score": best_match["match_score"],
                        "person_source_url": best_match["person"]["source_url"],
                    }
                )

        ratio = round((numerator / denominator) if denominator else 0.0, 4)
        metrics_units.append(
            {
                "label": label,
                "window_type": window_type,
                "research_article_count": denominator,
                "matched_article_count": numerator,
                "ratio": ratio,
            }
        )

    expected_window = "issue" if publication_model == "issue_based" else "calendar_year"
    measured_units = [u for u in metrics_units if u["window_type"] == expected_window]
    max_ratio = max((u["ratio"] for u in measured_units), default=0.0)
    result, limitations = _classify_decision(publication_model, measured_units, max_ratio)
    confidence = _confidence_score(result, matched_articles, limitations)
    explanation_en = _explanation(result, len(measured_units), max_ratio, limitations)

    evidence = _sanitize_evidence(submission.get("evidence", []))
    source_urls = submission.get("source_urls", {})
    reviewer_urls = source_urls.get("reviewers", []) if isinstance(source_urls, dict) else []
    if not reviewer_urls:
        evidence.append(
            {
                "kind": "crawl_note",
                "url": submission.get("journal_homepage_url", ""),
                "excerpt": "Reviewer list URL was not provided. Matching used editor and editorial board names only.",
                "locator_hint": "submission.source_urls.reviewers",
            }
        )

    return {
        "rule_id": RULE_ID,
        "version": RULE_VERSION,
        "result": result,
        "confidence": confidence,
        "crawl_timestamp_utc": submission.get("crawl_timestamp_utc", _now_iso_utc()),
        "publication_model": publication_model,
        "computed_metrics": {
            "units": measured_units,
            "max_ratio_observed": max_ratio,
            "threshold_ratio": THRESHOLD,
            "all_units_within_threshold": all(unit["ratio"] <= THRESHOLD for unit in measured_units) if measured_units else False,
        },
        "matched_articles": matched_articles,
        "evidence": evidence,
        "explanation_en": explanation_en,
        "limitations": limitations,
    }
