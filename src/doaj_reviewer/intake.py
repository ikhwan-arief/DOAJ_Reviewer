"""Build structured submission from raw URL-oriented input."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import re
import time
from typing import Any
from urllib.parse import urlparse

from .endogeny import normalize_name
from .web import (
    ParsedDocument,
    detect_waf_challenge,
    fetch_parsed_document_with_fallback,
    flatten_meta_values,
    safe_excerpt,
    same_domain,
    top_lines,
    url_path,
)


DEFAULT_TIMEOUT_SECONDS = 18
DEFAULT_MAX_ARTICLES_PER_UNIT = 40
DEFAULT_MAX_LINK_CANDIDATES = 120
DEFAULT_DOMAIN_MIN_DELAY_SECONDS = 0.35
DEFAULT_FETCH_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.8
RETRYABLE_STATUS_CODES = {403, 429, 503}
EXCLUDED_ARTICLE_TYPE_TERMS = {
    "editorial",
    "correction",
    "corrigendum",
    "erratum",
    "retraction",
    "letter",
    "news",
    "book review",
}
ROLE_KEYWORDS = {
    "editor in chief": "editor",
    "managing editor": "editor",
    "editorial board": "editorial_board_member",
    "reviewer": "reviewer",
}
POLICY_HINT_KEYS = (
    "open_access_statement",
    "issn_consistency",
    "publisher_identity",
    "license_terms",
    "copyright_author_rights",
    "peer_review_policy",
    "plagiarism_policy",
    "aims_scope",
    "publication_fees_disclosure",
    "archiving_policy",
    "repository_policy",
    "instructions_for_authors",
)
STOPWORDS = {
    "journal",
    "editor",
    "reviewer",
    "board",
    "volume",
    "issue",
    "university",
    "department",
    "faculty",
    "articles",
    "research",
    "authors",
    "about",
    "scope",
    "policy",
    "ethics",
    "open",
    "access",
}
PERSON_PATTERN = re.compile(r"[A-Z][A-Za-z'`\-]+(?:\s+[A-Z][A-Za-z'`\-]+){1,4}")
AFFILIATION_KEYWORDS = {
    "university",
    "institute",
    "department",
    "faculty",
    "school",
    "college",
    "hospital",
    "center",
    "centre",
    "academy",
    "press",
    "laboratory",
    "laboratoire",
    "research",
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


def _build_throttled_fetcher(
    base_fetcher,
    min_delay_seconds: float = DEFAULT_DOMAIN_MIN_DELAY_SECONDS,
    max_retries: int = DEFAULT_FETCH_MAX_RETRIES,
    retry_base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
):
    domain_next_allowed: dict[str, float] = {}
    retries = max(1, int(max_retries))
    min_delay = max(0.0, float(min_delay_seconds))
    base_delay = max(0.0, float(retry_base_delay_seconds))

    def _sleep_for_domain(domain: str) -> None:
        if not domain or min_delay <= 0:
            return
        wait_until = domain_next_allowed.get(domain, 0.0)
        now = time.monotonic()
        if wait_until > now:
            time.sleep(wait_until - now)

    def _mark_domain_visit(domain: str) -> None:
        if not domain or min_delay <= 0:
            return
        domain_next_allowed[domain] = time.monotonic() + min_delay

    def _fetch(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        domain = (urlparse(url).netloc or "").lower()
        last_exc: Exception | None = None

        for attempt in range(retries):
            _sleep_for_domain(domain)
            try:
                doc = base_fetcher(url, timeout_seconds=timeout_seconds)
                _mark_domain_visit(domain)
                if doc.status_code in RETRYABLE_STATUS_CODES and attempt < retries - 1:
                    if base_delay > 0:
                        time.sleep(base_delay * (2**attempt))
                    continue
                return doc
            except Exception as exc:
                _mark_domain_visit(domain)
                last_exc = exc
                if attempt >= retries - 1:
                    break
                if base_delay > 0:
                    time.sleep(base_delay * (2**attempt))

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Failed to fetch URL after {retries} attempt(s): {url}")

    return _fetch


def _waf_crawl_note(url: str, locator_hint: str, detection: dict[str, Any]) -> dict[str, str]:
    provider = str(detection.get("provider", "")).strip() or "unknown provider"
    reason = str(detection.get("reason", "")).strip() or "challenge page detected"
    excerpt = f"WAF/anti-bot challenge detected ({provider}): {reason}."
    return {
        "kind": "crawl_note",
        "url": url,
        "excerpt": safe_excerpt(excerpt, limit=280),
        "locator_hint": locator_hint,
    }


def _normalize_manual_policy_pages(raw_submission: dict[str, Any]) -> list[dict[str, str]]:
    raw_items = raw_submission.get("manual_policy_pages", [])
    if not isinstance(raw_items, list):
        return []

    out: list[dict[str, str]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        hint = str(item.get("rule_hint", "")).strip()
        text = str(item.get("text", "")).strip()
        title = str(item.get("title", "")).strip() or f"Manual fallback text ({hint})"
        source_label = str(item.get("source_label", "")).strip() or f"manual://{hint}/{index}"
        if "://" not in source_label:
            source_label = f"manual://{hint}/{index}"

        if hint not in POLICY_HINT_KEYS:
            continue
        if not text:
            continue

        out.append(
            {
                "rule_hint": hint,
                "url": source_label,
                "title": title[:180],
                "text": text[:120000],
            }
        )
    return out


def _looks_like_person_name(raw_name: str) -> bool:
    if not raw_name:
        return False
    name = raw_name.strip()
    if len(name) < 4 or len(name) > 90:
        return False
    if any(ch.isdigit() for ch in name):
        return False
    parts = [part for part in re.split(r"\s+", name) if part]
    if len(parts) < 2 or len(parts) > 5:
        return False
    normalized_parts = [re.sub(r"[^a-z]", "", part.lower()) for part in parts]
    if any(part in STOPWORDS for part in normalized_parts if part):
        return False
    alpha_len = sum(c.isalpha() for c in name)
    if alpha_len < 4:
        return False
    upper_starts = sum(1 for part in parts if part[0].isupper())
    return upper_starts >= max(2, len(parts) - 1)


def _find_role_from_line(line: str, default_role: str) -> str:
    low = line.lower()
    for keyword, role in ROLE_KEYWORDS.items():
        if keyword in low:
            return role
    if "editor" in low and "reviewer" not in low:
        return "editor"
    return default_role


def _extract_person_names_from_line(line: str) -> list[str]:
    candidates = [match.strip() for match in PERSON_PATTERN.findall(line)]
    return [candidate for candidate in candidates if _looks_like_person_name(candidate)]


def _clean_affiliation(text: str) -> str:
    value = re.sub(r"\s+", " ", text or "").strip(" -,:;|()[]")
    return value[:180]


def _looks_like_affiliation(text: str) -> bool:
    value = _clean_affiliation(text).lower()
    if len(value) < 6:
        return False
    if value.startswith(("editor", "reviewer", "board", "chief")):
        return False
    return any(keyword in value for keyword in AFFILIATION_KEYWORDS)


def _extract_affiliation_from_line(line: str, person_name: str) -> str:
    raw = line or ""
    name = person_name or ""
    candidate = ""

    if name and name in raw:
        tail = raw.split(name, 1)[1]
        candidate = _clean_affiliation(tail)
        if _looks_like_affiliation(candidate):
            return candidate

    if "-" in raw:
        right = _clean_affiliation(raw.split("-", 1)[1])
        if _looks_like_affiliation(right):
            return right
    if "," in raw:
        right = _clean_affiliation(raw.split(",", 1)[1])
        if _looks_like_affiliation(right):
            return right

    return ""


def extract_role_people_from_document(doc: ParsedDocument, default_role: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in doc.text.splitlines() if line.strip()]
    people: list[dict[str, str]] = []
    seen = set()
    active_role = default_role

    def _append_person(name: str, role: str, affiliation: str) -> None:
        key = (normalize_name(name), role)
        if key in seen:
            if affiliation:
                for item in people:
                    if normalize_name(item.get("name", "")) == key[0] and item.get("role", "") == role:
                        if not str(item.get("affiliation", "")).strip():
                            item["affiliation"] = affiliation
                        break
            return
        seen.add(key)
        payload = {
            "name": name,
            "role": role,
            "source_url": doc.url,
        }
        if affiliation:
            payload["affiliation"] = affiliation
        people.append(payload)

    for line in lines:
        active_role = _find_role_from_line(line, active_role)

        # Pattern: "Jane Smith - Editor in Chief"
        if "-" in line or "," in line:
            primary = re.split(r"[-,;|]", line, maxsplit=1)[0].strip()
            if _looks_like_person_name(primary):
                _append_person(primary, active_role, _extract_affiliation_from_line(line, primary))

        for candidate in _extract_person_names_from_line(line):
            _append_person(candidate, active_role, _extract_affiliation_from_line(line, candidate))

    return people


def _article_link_score(link: str) -> int:
    path = url_path(link)
    score = 0

    positive_tokens = ["/article", "/view/", "/doi/", "/full", "/abs", "/pdf"]
    for token in positive_tokens:
        if token in path:
            score += 3
    if "article" in path:
        score += 2
    if any(token in path for token in ["/issue/", "/volume/", "/vol", "/archives"]):
        score += 1

    negative_tokens = [
        "/about",
        "/editorial",
        "/reviewer",
        "/author",
        "/guideline",
        "/policy",
        "/login",
        "/register",
        "/search",
        "/announcement",
        "/contact",
    ]
    for token in negative_tokens:
        if token in path:
            score -= 3

    return score


def _extract_publication_date(doc: ParsedDocument) -> str | None:
    values = flatten_meta_values(
        doc.meta,
        [
            "citation_publication_date",
            "citation_date",
            "dc.date",
            "prism.publicationdate",
            "article:published_time",
        ],
    )
    for value in values:
        value = value.strip()
        if not value:
            continue
        return value
    return None


def _extract_article_type(doc: ParsedDocument) -> str:
    values = flatten_meta_values(doc.meta, ["citation_article_type", "dc.type", "article:section"])
    if values:
        return values[0].strip()
    return ""


def _is_research_article(article_type: str, title: str) -> bool:
    blob = f"{article_type} {title}".lower()
    for term in EXCLUDED_ARTICLE_TYPE_TERMS:
        if term in blob:
            return False
    return True


def extract_article_from_document(doc: ParsedDocument) -> dict[str, Any] | None:
    authors = flatten_meta_values(doc.meta, ["citation_author", "dc.creator", "dc.contributor.author", "author"])
    title_candidates = flatten_meta_values(doc.meta, ["citation_title", "og:title", "twitter:title"])
    title = title_candidates[0].strip() if title_candidates else doc.title.strip()
    article_type = _extract_article_type(doc)

    if not authors:
        return None
    if not title:
        title = doc.url
    if not _is_research_article(article_type, title):
        return None

    return {
        "title": title,
        "url": doc.url,
        "authors": authors,
        "article_type": article_type,
        "published_date": _extract_publication_date(doc),
    }


def _pick_article_links(issue_doc: ParsedDocument, journal_homepage_url: str, max_links: int) -> list[str]:
    picks: list[tuple[int, str]] = []
    seen = set()
    issue_path = url_path(issue_doc.url)

    for link in issue_doc.links:
        if link in seen:
            continue
        seen.add(link)

        if not same_domain(link, journal_homepage_url):
            continue
        if "#" in link:
            continue
        if link.lower().endswith((".jpg", ".png", ".gif", ".svg", ".css", ".js")):
            continue
        if url_path(link) == issue_path:
            continue

        score = _article_link_score(link)
        if score >= 2:
            picks.append((score, link))

    picks.sort(key=lambda item: (-item[0], item[1]))
    return [link for _, link in picks[:max_links]]


def collect_research_articles_from_unit(
    unit_url: str,
    journal_homepage_url: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_link_candidates: int = DEFAULT_MAX_LINK_CANDIDATES,
    max_articles: int = DEFAULT_MAX_ARTICLES_PER_UNIT,
    fetcher=None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if fetcher is None:
        base_fetcher = lambda url, timeout_seconds=DEFAULT_TIMEOUT_SECONDS: fetch_parsed_document_with_fallback(
            url=url, timeout_seconds=timeout_seconds, js_mode="auto"
        )
        fetcher = _build_throttled_fetcher(base_fetcher)

    unit_doc = fetcher(unit_url, timeout_seconds=timeout_seconds)
    unit_waf = detect_waf_challenge(unit_doc)
    if unit_waf.get("blocked", False):
        evidence = [_waf_crawl_note(unit_url, "unit-waf-blocked", unit_waf)]
        unit = {
            "label": unit_doc.title.strip() or unit_url,
            "window_type": "issue",
            "source_url": unit_url,
            "research_articles": [],
        }
        return unit, evidence

    unit_label = unit_doc.title.strip() or unit_url
    evidence: list[dict[str, str]] = [
        {
            "kind": "issue_listing",
            "url": unit_url,
            "excerpt": safe_excerpt(" | ".join(top_lines(unit_doc.text, limit=4))),
            "locator_hint": "issue-page-top-lines",
        }
    ]
    candidate_links = _pick_article_links(unit_doc, journal_homepage_url, max_links=max_link_candidates)
    articles: list[dict[str, Any]] = []
    seen_urls = set()

    for article_url in candidate_links:
        if len(articles) >= max_articles:
            break
        if article_url in seen_urls:
            continue
        seen_urls.add(article_url)
        try:
            article_doc = fetcher(article_url, timeout_seconds=timeout_seconds)
        except Exception:
            continue
        article_waf = detect_waf_challenge(article_doc)
        if article_waf.get("blocked", False):
            evidence.append(_waf_crawl_note(article_url, "article-waf-blocked", article_waf))
            continue
        article = extract_article_from_document(article_doc)
        if article is None:
            continue
        articles.append(article)

    unit = {
        "label": unit_label,
        "window_type": "issue",
        "source_url": unit_url,
        "research_articles": [
            {
                "title": article["title"],
                "url": article["url"],
                "authors": article["authors"],
                "article_type": article.get("article_type", ""),
                "doi": "",
                "published_date": article.get("published_date"),
            }
            for article in articles
        ],
    }
    return unit, evidence


def _year_from_date_text(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", value)
    if not match:
        return None
    year = int(match.group(0))
    if year < 1900 or year > 2100:
        return None
    return year


def collect_policy_pages(
    source_urls: dict[str, Any],
    timeout_seconds: int,
    fetcher,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    policy_pages: list[dict[str, str]] = []
    evidence: list[dict[str, str]] = []

    for hint in POLICY_HINT_KEYS:
        urls = list(source_urls.get(hint, []))
        for url in urls:
            try:
                doc = fetcher(url, timeout_seconds=timeout_seconds)
            except Exception:
                evidence.append(
                    {
                        "kind": "crawl_note",
                        "url": url,
                        "excerpt": f"Failed to fetch policy page for {hint}.",
                        "locator_hint": "policy-fetch-error",
                    }
                )
                continue
            detection = detect_waf_challenge(doc)
            if detection.get("blocked", False):
                evidence.append(_waf_crawl_note(url, f"policy-waf-blocked-{hint}", detection))
                continue

            policy_pages.append(
                {
                    "rule_hint": hint,
                    "url": url,
                    "title": doc.title.strip() or url,
                    "text": doc.text[:120000],
                }
            )
            evidence.append(
                {
                    "kind": "policy_text",
                    "url": url,
                    "excerpt": safe_excerpt(" | ".join(top_lines(doc.text, limit=4))),
                    "locator_hint": f"policy-page-{hint}",
                }
            )

    return policy_pages, evidence


def build_structured_submission_from_raw(
    raw_submission: dict[str, Any],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_articles_per_unit: int = DEFAULT_MAX_ARTICLES_PER_UNIT,
    fetcher=None,
    js_mode: str = "auto",
) -> dict[str, Any]:
    if fetcher is None:
        def base_fetcher(url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
            return fetch_parsed_document_with_fallback(url=url, timeout_seconds=timeout_seconds, js_mode=js_mode)

        fetcher = _build_throttled_fetcher(base_fetcher)

    submission_id = str(raw_submission.get("submission_id", ""))
    homepage = str(raw_submission.get("journal_homepage_url", ""))
    publication_model = str(raw_submission.get("publication_model", "issue_based"))
    source_urls = raw_submission.get("source_urls", {})

    editorial_urls = list(source_urls.get("editorial_board", []))
    reviewer_urls = list(source_urls.get("reviewers", []))
    latest_content_urls = list(source_urls.get("latest_content", []))
    archives_urls = list(source_urls.get("archives", []))
    open_access_urls = list(source_urls.get("open_access_statement", []))
    peer_review_policy_urls = list(source_urls.get("peer_review_policy", []))
    license_terms_urls = list(source_urls.get("license_terms", []))
    copyright_author_rights_urls = list(source_urls.get("copyright_author_rights", []))
    publication_fees_disclosure_urls = list(source_urls.get("publication_fees_disclosure", []))
    publisher_identity_urls = list(source_urls.get("publisher_identity", []))
    issn_consistency_urls = list(source_urls.get("issn_consistency", []))
    plagiarism_policy_urls = list(source_urls.get("plagiarism_policy", []))
    aims_scope_urls = list(source_urls.get("aims_scope", []))
    archiving_policy_urls = list(source_urls.get("archiving_policy", []))
    repository_policy_urls = list(source_urls.get("repository_policy", []))
    instructions_for_authors_urls = list(source_urls.get("instructions_for_authors", []))

    evidence: list[dict[str, str]] = []
    role_people: list[dict[str, str]] = []
    dedupe_people = set()
    policy_pages, policy_evidence = collect_policy_pages(
        source_urls=source_urls,
        timeout_seconds=timeout_seconds,
        fetcher=fetcher,
    )
    evidence.extend(policy_evidence)
    manual_policy_pages = _normalize_manual_policy_pages(raw_submission)
    if manual_policy_pages:
        policy_pages.extend(manual_policy_pages)
        for page in manual_policy_pages:
            evidence.append(
                {
                    "kind": "policy_text",
                    "url": page["url"],
                    "excerpt": safe_excerpt(" | ".join(top_lines(page["text"], limit=4))),
                    "locator_hint": f"manual-policy-{page['rule_hint']}",
                }
            )

    for url in editorial_urls:
        try:
            doc = fetcher(url, timeout_seconds=timeout_seconds)
        except Exception:
            evidence.append(
                {
                    "kind": "crawl_note",
                    "url": url,
                    "excerpt": "Failed to fetch editorial board page.",
                    "locator_hint": "fetch-error",
                }
            )
            continue
        detection = detect_waf_challenge(doc)
        if detection.get("blocked", False):
            evidence.append(_waf_crawl_note(url, "editorial-waf-blocked", detection))
            continue
        names = extract_role_people_from_document(doc, default_role="editorial_board_member")
        for person in names:
            key = (normalize_name(person["name"]), person["role"])
            if key in dedupe_people:
                continue
            dedupe_people.add(key)
            role_people.append(person)
        policy_pages.append(
            {
                "rule_hint": "editorial_board",
                "url": url,
                "title": doc.title.strip() or url,
                "text": doc.text[:120000],
            }
        )
        evidence.append(
            {
                "kind": "editor_list",
                "url": url,
                "excerpt": safe_excerpt(" | ".join(top_lines(doc.text, limit=3))),
                "locator_hint": "editorial-page-top-lines",
            }
        )

    for url in reviewer_urls:
        try:
            doc = fetcher(url, timeout_seconds=timeout_seconds)
        except Exception:
            evidence.append(
                {
                    "kind": "crawl_note",
                    "url": url,
                    "excerpt": "Failed to fetch reviewer page.",
                    "locator_hint": "fetch-error",
                }
            )
            continue
        detection = detect_waf_challenge(doc)
        if detection.get("blocked", False):
            evidence.append(_waf_crawl_note(url, "reviewer-waf-blocked", detection))
            continue
        names = extract_role_people_from_document(doc, default_role="reviewer")
        for person in names:
            key = (normalize_name(person["name"]), person["role"])
            if key in dedupe_people:
                continue
            dedupe_people.add(key)
            role_people.append(person)
        evidence.append(
            {
                "kind": "reviewer_list",
                "url": url,
                "excerpt": safe_excerpt(" | ".join(top_lines(doc.text, limit=3))),
                "locator_hint": "reviewer-page-top-lines",
            }
        )

    units: list[dict[str, Any]] = []
    if publication_model == "issue_based":
        unit_urls = latest_content_urls[:2]
        for unit_url in unit_urls:
            try:
                unit, unit_evidence = collect_research_articles_from_unit(
                    unit_url=unit_url,
                    journal_homepage_url=homepage,
                    timeout_seconds=timeout_seconds,
                    max_articles=max_articles_per_unit,
                    fetcher=fetcher,
                )
                units.append(unit)
                evidence.extend(unit_evidence)
            except Exception:
                evidence.append(
                    {
                        "kind": "crawl_note",
                        "url": unit_url,
                        "excerpt": "Failed to fetch unit page or article extraction failed.",
                        "locator_hint": "unit-fetch-error",
                    }
                )
    else:
        target_year = datetime.now(timezone.utc).year - 1
        aggregate_articles: list[dict[str, Any]] = []
        candidate_unit_urls = latest_content_urls + archives_urls
        visited = set()
        for unit_url in candidate_unit_urls:
            if unit_url in visited:
                continue
            visited.add(unit_url)
            try:
                unit, unit_evidence = collect_research_articles_from_unit(
                    unit_url=unit_url,
                    journal_homepage_url=homepage,
                    timeout_seconds=timeout_seconds,
                    max_articles=max_articles_per_unit,
                    fetcher=fetcher,
                )
            except Exception:
                evidence.append(
                    {
                        "kind": "crawl_note",
                        "url": unit_url,
                        "excerpt": "Failed to fetch continuous model unit candidate.",
                        "locator_hint": "continuous-fetch-error",
                    }
                )
                continue
            evidence.extend(unit_evidence)
            for article in unit["research_articles"]:
                year = _year_from_date_text(str(article.get("published_date", "")))
                if year == target_year or year is None:
                    aggregate_articles.append(article)
        units.append(
            {
                "label": str(target_year),
                "window_type": "calendar_year",
                "source_url": candidate_unit_urls[0] if candidate_unit_urls else homepage,
                "research_articles": aggregate_articles,
            }
        )
        evidence.append(
            {
                "kind": "crawl_note",
                "url": homepage,
                "excerpt": f"Continuous publication mode evaluated for calendar year {target_year}.",
                "locator_hint": "continuous-year-window",
            }
        )

    if not role_people:
        evidence.append(
            {
                "kind": "crawl_note",
                "url": homepage,
                "excerpt": "No editor/board/reviewer names could be extracted from provided role pages.",
                "locator_hint": "role-people-empty",
            }
        )

    return {
        "submission_id": submission_id,
        "journal_homepage_url": homepage,
        "publication_model": publication_model,
        "crawl_timestamp_utc": _now_iso_utc(),
        "source_urls": {
            "editorial_board": editorial_urls,
            "reviewers": reviewer_urls,
            "latest_content": latest_content_urls,
            "archives": archives_urls,
            "open_access_statement": open_access_urls,
            "peer_review_policy": peer_review_policy_urls,
            "license_terms": license_terms_urls,
            "copyright_author_rights": copyright_author_rights_urls,
            "publication_fees_disclosure": publication_fees_disclosure_urls,
            "publisher_identity": publisher_identity_urls,
            "issn_consistency": issn_consistency_urls,
            "plagiarism_policy": plagiarism_policy_urls,
            "aims_scope": aims_scope_urls,
            "archiving_policy": archiving_policy_urls,
            "repository_policy": repository_policy_urls,
            "instructions_for_authors": instructions_for_authors_urls,
        },
        "role_people": role_people,
        "units": units,
        "evidence": evidence,
        "policy_pages": policy_pages,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build structured submission JSON from raw URL-based submission.")
    parser.add_argument("--input", required=True, help="Path to raw submission JSON.")
    parser.add_argument("--output", required=True, help="Path to output structured submission JSON.")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout per request.")
    parser.add_argument(
        "--max-articles-per-unit",
        type=int,
        default=DEFAULT_MAX_ARTICLES_PER_UNIT,
        help="Maximum articles to keep per measurement unit.",
    )
    parser.add_argument(
        "--js-mode",
        choices=["off", "auto", "on"],
        default="auto",
        help="JS rendering mode for fetching pages (off, auto fallback, on).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_submission = _load_json(Path(args.input))
    structured = build_structured_submission_from_raw(
        raw_submission=raw_submission,
        timeout_seconds=args.timeout_seconds,
        max_articles_per_unit=args.max_articles_per_unit,
        js_mode=args.js_mode,
    )
    _write_json(Path(args.output), structured)
    role_count = len(structured.get("role_people", []))
    unit_count = len(structured.get("units", []))
    article_total = sum(len(unit.get("research_articles", [])) for unit in structured.get("units", []))
    print(f"Submission: {structured.get('submission_id', '')}")
    print(f"Role people extracted: {role_count}")
    print(f"Units extracted: {unit_count}")
    print(f"Research articles extracted: {article_total}")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
