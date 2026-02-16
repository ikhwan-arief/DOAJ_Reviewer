"""Evaluators for DOAJ must-rules beyond endogeny."""

from __future__ import annotations

import re
from typing import Any

INSTITUTION_KEYWORDS = (
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
    "research",
)

LICENSE_PATTERNS = {
    "CC BY": r"\bcc\s*by\b",
    "CC BY-SA": r"\bcc\s*by\s*-\s*sa\b",
    "CC BY-ND": r"\bcc\s*by\s*-\s*nd\b",
    "CC BY-NC": r"\bcc\s*by\s*-\s*nc\b",
    "CC BY-NC-SA": r"\bcc\s*by\s*-\s*nc\s*-\s*sa\b",
    "CC BY-NC-ND": r"\bcc\s*by\s*-\s*nc\s*-\s*nd\b",
    "CC0": r"\bcc0\b",
    "Public domain": r"\bpublic domain\b",
    "Publisher's own license": r"\bpublisher'?s?\s+own\s+licen[sc]e\b",
}

PEER_REVIEW_TYPE_PATTERNS = {
    "Editorial review": r"\beditorial review\b",
    "Peer review": r"\bpeer review\b",
    "Anonymous peer review": r"\banonymous peer review\b|\bsingle blind\b|\bblind peer review\b",
    "Double anonymous peer review": r"\bdouble anonymous peer review\b|\bdouble blind\b",
    "Post-publication peer review": r"\bpost-?publication peer review\b",
    "Open peer review": r"\bopen peer review\b",
    "Other": r"\bother review\b",
}


def _get_policy_urls(submission: dict[str, Any], rule_hint: str) -> list[str]:
    source_urls = submission.get("source_urls", {})
    if not isinstance(source_urls, dict):
        return []
    urls = source_urls.get(rule_hint, [])
    if not isinstance(urls, list):
        return []
    return [str(url) for url in urls if isinstance(url, str) and url]


def _get_policy_pages(submission: dict[str, Any], rule_hint: str) -> list[dict[str, str]]:
    pages = submission.get("policy_pages", [])
    if not isinstance(pages, list):
        return []
    out: list[dict[str, str]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        if str(page.get("rule_hint", "")) != rule_hint:
            continue
        url = str(page.get("url", ""))
        text = str(page.get("text", ""))
        title = str(page.get("title", ""))
        if not url:
            continue
        out.append({"url": url, "text": text, "title": title})
    return out


def _text_blob(pages: list[dict[str, str]]) -> str:
    chunks: list[str] = []
    for page in pages:
        title = page.get("title", "")
        text = page.get("text", "")
        chunks.append(f"{title}\n{text}")
    return "\n".join(chunks).lower()


def _contains_any(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def _count_any(text: str, patterns: list[str]) -> int:
    count = 0
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            count += 1
    return count


def _waf_block_notes(submission: dict[str, Any], rule_hint: str) -> list[str]:
    evidence = submission.get("evidence", [])
    if not isinstance(evidence, list):
        return []
    waf_locator = f"policy-waf-blocked-{rule_hint}"
    out: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind", "")) != "crawl_note":
            continue
        locator = str(item.get("locator_hint", ""))
        if locator != waf_locator:
            continue
        excerpt = str(item.get("excerpt", "")).strip()
        if excerpt:
            out.append(excerpt)
    return out


def _missing_policy_result(rule_id: str, rule_hint: str, submission: dict[str, Any]) -> dict[str, Any]:
    # The caller may still add evidence URLs from source_urls in the returned object.
    waf_notes = _waf_block_notes(submission, rule_hint)
    if waf_notes:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.42,
            "notes": (
                f"Policy URL appears blocked by WAF/anti-bot challenge for `{rule_hint}`. "
                f"Use manual fallback text/PDF and human review. {waf_notes[0]}"
            ),
            "evidence_urls": [],
        }
    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.25,
        "notes": f"No policy text was extracted for `{rule_hint}` URLs.",
        "evidence_urls": [],
    }


def _clean_text_value(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" -,:;|()[]")


def _extract_publisher_name_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    patterns = [
        r"\bpublished by\s*[:\-]?\s*([^\n\.]{4,100})",
        r"\bpublisher\s*[:\-]?\s*([^\n\.]{4,100})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            name = _clean_text_value(match.group(1))
            if len(name) < 4:
                continue
            if name.lower().startswith(("contact", "address", "email")):
                continue
            if name not in candidates:
                candidates.append(name)
    return candidates


def _publisher_signatures(submission: dict[str, Any]) -> set[str]:
    pages = _get_policy_pages(submission, "publisher_identity")
    signatures: set[str] = set()
    for page in pages:
        blob = f"{page.get('title', '')}\n{page.get('text', '')}"
        for name in _extract_publisher_name_candidates(blob):
            normalized = re.sub(r"[^a-z0-9 ]", " ", name.lower())
            normalized = re.sub(r"\s+", " ", normalized).strip()
            for token in normalized.split():
                if len(token) >= 4:
                    signatures.add(token)
    return signatures


def _is_same_as_publisher(affiliation: str, publisher_signatures: set[str]) -> bool | None:
    value = _clean_text_value(affiliation).lower()
    if not value:
        return None
    if not any(keyword in value for keyword in INSTITUTION_KEYWORDS):
        return None
    words = {token for token in re.sub(r"[^a-z0-9 ]", " ", value).split() if len(token) >= 4}
    if not words:
        return None
    if not publisher_signatures:
        return None
    return bool(words & publisher_signatures)


def _count_group_affiliation_composition(
    people: list[dict[str, Any]], publisher_signatures: set[str]
) -> tuple[int, int, int]:
    same = 0
    outside = 0
    unknown = 0
    for item in people:
        affiliation = _clean_text_value(str(item.get("affiliation", "")))
        if not affiliation:
            unknown += 1
            continue
        same_flag = _is_same_as_publisher(affiliation, publisher_signatures)
        if same_flag is True:
            same += 1
        elif same_flag is False:
            outside += 1
        else:
            unknown += 1
    return same, outside, unknown


def evaluate_open_access_statement(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.open_access_statement.v1"
    rule_hint = "open_access_statement"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = _get_policy_urls(submission, rule_hint)
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]

    open_access_signals = [
        r"\bopen access\b",
        r"\bfreely available\b",
        r"\bfree access\b",
        r"\bwithout charge\b",
    ]
    reuse_signals = [
        r"\bread\b",
        r"\bdownload\b",
        r"\bcopy\b",
        r"\bdistribut(e|ion)\b",
        r"\breuse\b",
        r"\breproduce\b",
        r"\blink to\b",
        r"\btext and data mining\b",
    ]
    license_signals = [
        r"\bcreative commons\b",
        r"\bcc by\b",
        r"\bcc by-sa\b",
        r"\bcc by-nd\b",
        r"\bcc by-nc\b",
        r"\bcc by-nc-sa\b",
        r"\bcc by-nc-nd\b",
        r"\bcc0\b",
        r"\bpublic domain\b",
    ]
    hard_negative_signals = [
        r"\bsubscription required\b",
        r"\bpaywall\b",
        r"\bembargo period\b",
        r"\bmembers only\b",
        r"\bpurchase\b",
        r"\baccess limited to subscribers\b",
        r"\bno open access\b",
    ]

    has_oa = _contains_any(text, open_access_signals)
    reuse_count = _count_any(text, reuse_signals)
    has_license = _contains_any(text, license_signals)
    has_negative = _contains_any(text, hard_negative_signals)
    all_rights_reserved = _contains_any(text, [r"\ball rights reserved\b"])

    if has_negative and not (has_oa and (has_license or reuse_count >= 3)):
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.88,
            "notes": "Open access statement includes restrictive access wording without sufficient OA/reuse rights wording.",
            "evidence_urls": evidence_urls,
        }

    if has_oa and (has_license or reuse_count >= 3) and not (all_rights_reserved and not has_license):
        confidence = 0.82 if has_license else 0.74
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": confidence,
            "notes": "Open access statement includes OA wording and reuse/license signals.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.58,
        "notes": "Open access wording exists but evidence is incomplete or ambiguous for DOAJ-level OA rights.",
        "evidence_urls": evidence_urls,
    }


def evaluate_peer_review_policy(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.peer_review_policy.v1"
    rule_hint = "peer_review_policy"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = _get_policy_urls(submission, rule_hint)
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]

    peer_review_signals = [
        r"\bpeer review\b",
        r"\bpeer-reviewed\b",
        r"\bdouble blind\b",
        r"\bdouble anonymous\b",
        r"\bsingle blind\b",
        r"\banonymous peer review\b",
        r"\bopen peer review\b",
        r"\bexternal reviewer\b",
        r"\bblind peer review\b",
    ]
    process_signals = [
        r"\breview process\b",
        r"\breviewed by\b",
        r"\beditorial decision\b",
        r"\brevision\b",
        r"\bmanuscript\b",
        r"\bacceptance\b",
    ]
    min_two_reviewer_signals = [
        r"\bat least\s+2\s+(independent\s+)?reviewers?\b",
        r"\bminimum\s+of\s+2\s+(independent\s+)?reviewers?\b",
        r"\btwo\s+(\w+\s+){0,2}reviewers?\b",
        r"\b2\s+(\w+\s+){0,2}reviewers?\b",
        r"\breviewed\s+by\s+at\s+least\s+two\b",
    ]
    fail_signals = [
        r"\bnot peer reviewed\b",
        r"\bno peer review\b",
    ]
    editorial_only_signal = r"\beditorial review only\b|\beditorial review\b"

    if _contains_any(text, fail_signals):
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.9,
            "notes": "Policy explicitly states there is no peer review.",
            "evidence_urls": evidence_urls,
        }

    has_peer_review = _contains_any(text, peer_review_signals)
    process_count = _count_any(text, process_signals)
    editorial_only = _contains_any(text, [editorial_only_signal])
    has_min_two = _contains_any(text, min_two_reviewer_signals)
    detected_types = [
        review_type
        for review_type, pattern in PEER_REVIEW_TYPE_PATTERNS.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    types_text = ", ".join(detected_types[:4]) if detected_types else "not specified"

    if has_peer_review and process_count >= 1 and has_min_two:
        confidence = 0.84 if process_count >= 2 else 0.76
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": confidence,
            "notes": f"Peer review policy is present. Detected type(s): {types_text}. Policy states at least two reviewers per article.",
            "evidence_urls": evidence_urls,
        }

    if has_peer_review and not has_min_two:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.61,
            "notes": f"Peer review type(s) detected ({types_text}) but no explicit statement of at least two reviewers per article.",
            "evidence_urls": evidence_urls,
        }

    if editorial_only and not has_peer_review:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.52,
            "notes": "Only editorial review wording detected; policy needs manual assessment (arts/humanities exception may apply).",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.56,
        "notes": f"Peer review policy is missing or too vague for automatic pass/fail. Detected type(s): {types_text}.",
        "evidence_urls": evidence_urls,
    }


def evaluate_license_terms(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.license_terms.v1"
    rule_hint = "license_terms"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = _get_policy_urls(submission, rule_hint)
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]

    cc_signals = [
        r"\bcreative commons\b",
        r"\bcc\b",
        r"\bcc0\b",
        r"\bpublic domain\b",
    ]
    publisher_license_signals = [
        r"\bpublisher'?s own license\b",
        r"\bjournal license\b",
        r"\blicense terms\b",
        r"\blicensing policy\b",
    ]
    negative_signals = [
        r"\bno license\b",
        r"\bwithout license\b",
    ]

    cc_count = _count_any(text, cc_signals)
    has_license_word = _contains_any(text, [r"\blicen[sc]e\b"])
    has_publisher_license = _contains_any(text, publisher_license_signals)
    has_negative = _contains_any(text, negative_signals)
    all_rights_reserved = _contains_any(text, [r"\ball rights reserved\b"])
    detected = [name for name, pattern in LICENSE_PATTERNS.items() if re.search(pattern, text, flags=re.IGNORECASE)]
    detected_text = ", ".join(detected[:5]) if detected else "none"

    if has_negative or (all_rights_reserved and cc_count == 0 and not has_publisher_license):
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.86,
            "notes": "License policy appears restrictive or missing open licensing terms.",
            "evidence_urls": evidence_urls,
        }

    if detected:
        confidence = 0.86 if len(detected) >= 2 else 0.8
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": confidence,
            "notes": f"Detected license option(s): {detected_text}.",
            "evidence_urls": evidence_urls,
        }

    if cc_count > 0:
        confidence = 0.84 if cc_count >= 2 else 0.78
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": confidence,
            "notes": "Creative Commons/public-domain licensing terms were detected.",
            "evidence_urls": evidence_urls,
        }

    if has_publisher_license and has_license_word:
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": 0.68,
            "notes": "Publisher-owned license terms were detected; manual policy quality review may still be needed.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.55,
        "notes": f"License wording exists but the allowed DOAJ options were not clearly identified (detected: {detected_text}).",
        "evidence_urls": evidence_urls,
    }


def evaluate_copyright_author_rights(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.copyright_author_rights.v1"
    rule_hint = "copyright_author_rights"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        # Fallback: many journals place author-rights wording on licensing pages.
        pages = _get_policy_pages(submission, "license_terms")
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = (
            _get_policy_urls(submission, rule_hint) or _get_policy_urls(submission, "license_terms")
        )
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]

    retain_signals = [
        r"\bauthors?\s+retain(s)?\s+(the\s+)?copyright\b",
        r"\bcopyright\s+remains?\s+with\s+the\s+authors?\b",
        r"\bauthors?\s+hold\s+copyright\b",
        r"\bauthors?\s+retain(s)?\s+publishing\s+rights?\b",
        r"\bnon-?exclusive\s+license\s+to\s+publish\b",
    ]
    transfer_signals = [
        r"\bauthors?\s+transfer(s|red)?\s+copyright\b",
        r"\bcopyright\s+is\s+transferred\s+to\s+the\s+publisher\b",
        r"\bauthors?\s+assign(s|ed)?\s+exclusive\s+rights?\b",
        r"\bpublisher\s+owns?\s+copyright\b",
        r"\bcopyright\s+belongs?\s+to\s+the\s+publisher\b",
    ]

    has_retain = _contains_any(text, retain_signals)
    has_transfer = _contains_any(text, transfer_signals)

    if has_retain and not has_transfer:
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": 0.81,
            "notes": "Policy states that authors retain copyright and/or full rights.",
            "evidence_urls": evidence_urls,
        }

    if has_transfer and not has_retain:
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.89,
            "notes": "Policy indicates copyright transfer or exclusive assignment to publisher.",
            "evidence_urls": evidence_urls,
        }

    if has_retain and has_transfer:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.45,
            "notes": "Conflicting author-rights statements were detected.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.56,
        "notes": "Author-rights wording is missing or too vague for automatic decision.",
        "evidence_urls": evidence_urls,
    }


def evaluate_publication_fees_disclosure(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.publication_fees_disclosure.v1"
    rule_hint = "publication_fees_disclosure"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        # Fallback pages often used for fee statements.
        pages = _get_policy_pages(submission, "open_access_statement") + _get_policy_pages(submission, "license_terms")
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = (
            _get_policy_urls(submission, rule_hint)
            or _get_policy_urls(submission, "open_access_statement")
            or _get_policy_urls(submission, "license_terms")
        )
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]

    no_fee_signals = [
        r"\bno\s+(article\s+processing\s+charge|apc|publication\s+fee|submission\s+fee|page\s+charge)s?\b",
        r"\bfree\s+of\s+charge\b",
        r"\bdoes\s+not\s+charge\b",
        r"\bwithout\s+fees?\b",
    ]
    fee_signals = [
        r"\barticle\s+processing\s+charge(s)?\b",
        r"\bapc(s)?\b",
        r"\bpublication\s+fee(s)?\b",
        r"\bsubmission\s+fee(s)?\b",
        r"\bpage\s+charge(s)?\b",
        r"\beditorial\s+processing\s+charge(s)?\b",
        r"\blanguage\s+editing\s+fee(s)?\b",
    ]
    fee_obligation_signals = [
        r"\bauthors?\s+(must|are\s+required\s+to)\s+pay\b",
        r"\bfee(s)?\s+(is|are)\s+charged\b",
        r"\bwe\s+charge\b",
        r"\bcharges?\s+apply\b",
    ]
    amount_signal = r"(\bUSD\b|\bEUR\b|\bIDR\b|\bGBP\b|\$\s?\d|\b\d{2,}\s?(usd|eur|idr|gbp)\b)"
    ambiguous_signals = [
        r"\bcontact\s+(the\s+)?editor\s+for\s+fee\b",
        r"\bfee\s+information\s+available\s+on\s+request\b",
        r"\bfees?\s+may\s+apply\b",
        r"\bto\s+be\s+determined\b",
    ]

    has_no_fee = _contains_any(text, no_fee_signals)
    has_fee_terms = _contains_any(text, fee_signals)
    has_fee_obligation = _contains_any(text, fee_obligation_signals)
    has_amount = _contains_any(text, [amount_signal])
    has_ambiguous = _contains_any(text, ambiguous_signals)

    if has_no_fee and has_fee_terms and not _contains_any(text, [r"\bno\s+apc\b", r"\bno\s+publication\s+fee\b"]):
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.44,
            "notes": "Potentially conflicting fee statements were detected.",
            "evidence_urls": evidence_urls,
        }

    if has_no_fee:
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": 0.82,
            "notes": "Policy explicitly states that there are no publication/APC fees.",
            "evidence_urls": evidence_urls,
        }

    if has_fee_terms and (has_fee_obligation or has_amount):
        confidence = 0.83 if has_amount else 0.74
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": confidence,
            "notes": "Policy explicitly discloses publication/APC fees.",
            "evidence_urls": evidence_urls,
        }

    if has_ambiguous and not (has_no_fee or has_fee_terms):
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.77,
            "notes": "Fee policy appears ambiguous and does not clearly disclose whether publication fees are charged.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.57,
        "notes": "Fee policy text is present but not explicit enough for automatic decision.",
        "evidence_urls": evidence_urls,
    }


def evaluate_publisher_identity(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.publisher_identity.v1"
    rule_hint = "publisher_identity"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        # Fallback pages that often include publisher details.
        pages = (
            _get_policy_pages(submission, "open_access_statement")
            + _get_policy_pages(submission, "peer_review_policy")
            + _get_policy_pages(submission, "license_terms")
        )
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = (
            _get_policy_urls(submission, rule_hint)
            or _get_policy_urls(submission, "open_access_statement")
            or _get_policy_urls(submission, "peer_review_policy")
            or _get_policy_urls(submission, "license_terms")
        )
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]

    name_signals = [
        r"\bpublisher\b",
        r"\bpublished by\b",
        r"\bjournal publisher\b",
        r"\bpublishing house\b",
        r"\buniversity press\b",
        r"\bsociety\b",
        r"\binstitute\b",
    ]
    contact_signals = [
        r"\bcontact\b",
        r"\be-?mail\b",
        r"@[a-z0-9\.\-]+\.[a-z]{2,}",
        r"\bphone\b",
        r"\btel\b",
        r"\bwhatsapp\b",
    ]
    address_signals = [
        r"\baddress\b",
        r"\bstreet\b",
        r"\broad\b",
        r"\bbuilding\b",
        r"\bcity\b",
        r"\bcountry\b",
        r"\bzip\b",
        r"\bpostal code\b",
    ]
    negative_signals = [
        r"\bpublisher information not available\b",
        r"\bpublisher not disclosed\b",
        r"\banonymous publisher\b",
    ]

    has_name = _contains_any(text, name_signals)
    has_contact = _contains_any(text, contact_signals)
    has_address = _contains_any(text, address_signals)
    has_negative = _contains_any(text, negative_signals)

    if has_negative and not (has_name and (has_contact or has_address)):
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.84,
            "notes": "Publisher identity appears undisclosed or explicitly unavailable.",
            "evidence_urls": evidence_urls,
        }

    if has_name and (has_contact or has_address):
        confidence = 0.82 if (has_contact and has_address) else 0.73
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": confidence,
            "notes": "Publisher identity is present with contact/address details.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.57,
        "notes": "Publisher information was detected but not sufficient for automatic verification.",
        "evidence_urls": evidence_urls,
    }


def _issn_check_digit_valid(issn: str) -> bool:
    candidate = re.sub(r"[^0-9Xx]", "", issn or "")
    if len(candidate) != 8:
        return False
    total = 0
    for idx, char in enumerate(candidate[:7]):
        if not char.isdigit():
            return False
        weight = 8 - idx
        total += int(char) * weight
    check_val = (11 - (total % 11)) % 11
    expected = "X" if check_val == 10 else str(check_val)
    actual = candidate[7].upper()
    return actual == expected


def _extract_issns(text: str) -> list[str]:
    return sorted(set(match.upper() for match in re.findall(r"\b\d{4}-\d{3}[0-9Xx]\b", text)))


def _extract_issn_mentions(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for match in re.finditer(r"\b\d{4}-\d{3}[0-9Xx]\b", text):
        issn = match.group(0).upper()
        start = max(0, match.start() - 45)
        end = min(len(text), match.end() + 45)
        context = text[start:end]
        low = context.lower()
        category = "unknown"
        if re.search(r"\b(e[-\s]?issn|online|electronic)\b", low):
            category = "electronic"
        elif re.search(r"\b(p[-\s]?issn|print)\b", low):
            category = "print"
        out.append({"issn": issn, "category": category})
    return out


def evaluate_issn_consistency(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.issn_consistency.v1"
    rule_hint = "issn_consistency"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        # Fallback pages where ISSNs are commonly listed.
        pages = (
            _get_policy_pages(submission, "publisher_identity")
            + _get_policy_pages(submission, "open_access_statement")
            + _get_policy_pages(submission, "peer_review_policy")
        )
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = (
            _get_policy_urls(submission, rule_hint)
            or _get_policy_urls(submission, "publisher_identity")
            or _get_policy_urls(submission, "open_access_statement")
            or _get_policy_urls(submission, "peer_review_policy")
        )
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]
    issns = _extract_issns(text)
    mentions = _extract_issn_mentions(text)

    if not issns:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.42,
            "notes": "No ISSN value was detected in the provided pages.",
            "evidence_urls": evidence_urls,
        }

    valid = [issn for issn in issns if _issn_check_digit_valid(issn)]
    invalid = [issn for issn in issns if issn not in valid]
    electronic_issns = sorted({item["issn"] for item in mentions if item["category"] == "electronic"})
    valid_electronic = [issn for issn in electronic_issns if issn in valid]
    invalid_electronic = [issn for issn in electronic_issns if issn in invalid]

    if valid_electronic and not invalid_electronic:
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": 0.86,
            "notes": f"Detected valid electronic ISSN value(s): {', '.join(valid_electronic[:4])}.",
            "evidence_urls": evidence_urls,
        }

    if invalid_electronic and not valid_electronic:
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.9,
            "notes": f"Electronic ISSN value(s) were detected but invalid: {', '.join(invalid_electronic[:4])}.",
            "evidence_urls": evidence_urls,
        }

    if valid and not invalid and not valid_electronic:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.62,
            "notes": f"Valid ISSN value(s) detected ({', '.join(valid[:4])}) but no explicit electronic ISSN marker was found.",
            "evidence_urls": evidence_urls,
        }

    if not valid and invalid:
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.86,
            "notes": f"Detected ISSN-like values but check digits are invalid: {', '.join(invalid[:4])}.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.53,
        "notes": "Mixed ISSN evidence was detected (including electronic/print variants); consistency needs manual confirmation.",
        "evidence_urls": evidence_urls,
    }


def evaluate_aims_scope(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.aims_scope.v1"
    rule_hint = "aims_scope"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = _get_policy_urls(submission, rule_hint)
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]

    heading_signals = [
        r"\baims?\s*&\s*scope\b",
        r"\baims?\s+and\s+scope\b",
        r"\bjournal\s+scope\b",
        r"\bfocus\s+and\s+scope\b",
    ]
    scope_signals = [
        r"\bthe\s+journal\s+publishes\b",
        r"\btopics?\s+include\b",
        r"\bsubject\s+areas?\b",
        r"\bmanuscripts?\s+in\b",
        r"\bfields?\s+of\b",
        r"\bcovers?\b",
    ]
    negative_signals = [
        r"\baims?\s+and\s+scope\s+not\s+available\b",
        r"\bno\s+aims?\s+and\s+scope\b",
        r"\bscope\s+not\s+defined\b",
    ]

    has_heading = _contains_any(text, heading_signals)
    scope_count = _count_any(text, scope_signals)
    has_negative = _contains_any(text, negative_signals)
    has_aim_or_focus = _contains_any(text, [r"\baims?\b", r"\bfocus\b"])
    has_scope_word = _contains_any(text, [r"\bscope\b"])

    if has_negative and not (has_heading or scope_count >= 2):
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.84,
            "notes": "Aims and scope appear missing or explicitly unavailable.",
            "evidence_urls": evidence_urls,
        }

    if has_heading and scope_count >= 1:
        if has_scope_word and not has_aim_or_focus:
            return {
                "rule_id": rule_id,
                "result": "need_human_review",
                "confidence": 0.63,
                "notes": "Scope information is present, but explicit aims/focus wording was not detected.",
                "evidence_urls": evidence_urls,
            }
        confidence = 0.82 if scope_count >= 2 else 0.74
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": confidence,
            "notes": "Aims and scope statement is present with topic/coverage details.",
            "evidence_urls": evidence_urls,
        }

    if has_heading:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.6,
            "notes": "Aims/scope heading is present but topical detail is limited.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.55,
        "notes": "Aims and scope wording is not explicit enough for automatic decision.",
        "evidence_urls": evidence_urls,
    }


def evaluate_editorial_board(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.editorial_board.v1"
    rule_hint = "editorial_board"
    pages = _get_policy_pages(submission, rule_hint)
    evidence_urls = [page["url"] for page in pages] if pages else _get_policy_urls(submission, rule_hint)
    text = _text_blob(pages) if pages else ""

    role_people = submission.get("role_people", [])
    if not isinstance(role_people, list):
        role_people = []

    board_people: list[dict[str, Any]] = []
    reviewer_people: list[dict[str, Any]] = []
    seen_board = set()
    seen_reviewer = set()
    for item in role_people:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", ""))
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        key = name.lower()
        if role in {"editor", "editorial_board_member"}:
            if key in seen_board:
                continue
            seen_board.add(key)
            board_people.append(item)
            continue
        if role == "reviewer":
            if key in seen_reviewer:
                continue
            seen_reviewer.add(key)
            reviewer_people.append(item)

    board_count = len(board_people)
    reviewer_count = len(reviewer_people)
    has_editor = any(str(item.get("role", "")) == "editor" for item in board_people)
    board_affiliations = [str(item.get("affiliation", "")).strip() for item in board_people if str(item.get("affiliation", "")).strip()]
    has_affiliation_field = bool(board_affiliations)
    affiliation_signals = [
        r"\buniversity\b",
        r"\binstitute\b",
        r"\bdepartment\b",
        r"\bfaculty\b",
        r"\bhospital\b",
        r"\bschool\b",
        r"\baffiliation\b",
        r"\bcountry\b",
    ]
    has_affiliation_text = _contains_any(text, affiliation_signals)
    publisher_signatures = _publisher_signatures(submission)
    board_same, board_outside, board_unknown = _count_group_affiliation_composition(
        board_people, publisher_signatures
    )
    reviewer_same, reviewer_outside, reviewer_unknown = _count_group_affiliation_composition(
        reviewer_people, publisher_signatures
    )
    reviewer_urls = _get_policy_urls(submission, "reviewers")
    reviewer_page_exists = bool(reviewer_urls)

    no_board_signals = [
        r"\bno\s+editorial\s+board\b",
        r"\beditorial\s+board\s+not\s+available\b",
    ]
    has_no_board = _contains_any(text, no_board_signals)

    if board_count == 0 and has_no_board:
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.87,
            "notes": "Editorial board appears unavailable.",
            "evidence_urls": evidence_urls,
        }

    if board_count == 0:
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.79,
            "notes": "No editorial board members could be identified.",
            "evidence_urls": evidence_urls,
        }

    notes: list[str] = []
    needs_human_review = False

    if not has_editor:
        needs_human_review = True
        notes.append("No explicit editor role was detected.")
    if board_count < 5:
        needs_human_review = True
        notes.append(f"Only {board_count} editorial board member(s) were extracted (target minimum: 5).")
    if not (has_affiliation_field or has_affiliation_text):
        needs_human_review = True
        notes.append("Editorial board affiliation evidence is weak or missing.")
    board_same_ratio = board_same / board_count if board_count else 0.0
    board_outside_ratio = board_outside / board_count if board_count else 0.0
    notes.append(
        "Editorial board affiliation composition (informational only): "
        f"{board_same}/{board_count} ({round(board_same_ratio * 100, 2)}%) same institution as publisher, "
        f"{board_outside}/{board_count} ({round(board_outside_ratio * 100, 2)}%) outside, "
        f"{board_unknown}/{board_count} unknown. No fixed composition threshold is applied to editorial board."
    )

    if reviewer_page_exists:
        if reviewer_count < 10:
            needs_human_review = True
            notes.append(f"Only {reviewer_count} reviewer name(s) were extracted (target minimum: 10).")
        else:
            known_total = reviewer_same + reviewer_outside
            same_ratio = reviewer_same / reviewer_count if reviewer_count else 0.0
            outside_ratio = reviewer_outside / reviewer_count if reviewer_count else 0.0
            notes.append(
                "Reviewer affiliation composition (enforced): "
                f"{reviewer_same}/{reviewer_count} ({round(same_ratio * 100, 2)}%) same institution, "
                f"{reviewer_outside}/{reviewer_count} ({round(outside_ratio * 100, 2)}%) outside, "
                f"{reviewer_unknown}/{reviewer_count} unknown."
            )
            if known_total < reviewer_count:
                needs_human_review = True
                notes.append(
                    f"Reviewer affiliation classification is incomplete ({known_total}/{reviewer_count} identified as inside/outside publisher institution)."
                )
            else:
                if same_ratio > 0.40 or outside_ratio < 0.60:
                    return {
                        "rule_id": rule_id,
                        "result": "fail",
                        "confidence": 0.83,
                        "notes": (
                            f"Reviewer affiliation composition is outside target range: "
                            f"{round(same_ratio * 100, 2)}% from publisher institution and "
                            f"{round(outside_ratio * 100, 2)}% outside (required: <=40% and >=60%)."
                        ),
                        "evidence_urls": evidence_urls + reviewer_urls,
                    }
                notes.append("Reviewer composition meets target range (<=40% same institution, >=60% outside).")
    else:
        notes.append("Reviewer page URL was not provided; reviewer composition check was skipped.")

    if needs_human_review:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.61,
            "notes": " ".join(notes),
            "evidence_urls": evidence_urls + reviewer_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "pass",
        "confidence": 0.8,
        "notes": "Editorial board minimum criteria are met. " + " ".join(notes),
        "evidence_urls": evidence_urls + reviewer_urls,
    }


def evaluate_instructions_for_authors(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.instructions_for_authors.v1"
    rule_hint = "instructions_for_authors"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        missing = _missing_policy_result(rule_id, rule_hint, submission)
        missing["evidence_urls"] = _get_policy_urls(submission, rule_hint)
        return missing

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]

    heading_signals = [
        r"\binstructions?\s+for\s+authors?\b",
        r"\bauthor\s+guidelines?\b",
        r"\bguide\s+for\s+authors?\b",
        r"\bsubmission\s+guidelines?\b",
    ]
    process_signals = [
        r"\bmanuscript\b",
        r"\bsubmission\b",
        r"\bformat\b",
        r"\breference\s+style\b",
        r"\bethics\b",
        r"\bplagiarism\b",
        r"\btemplate\b",
        r"\bpeer\s+review\b",
    ]
    negative_signals = [
        r"\binstructions?\s+not\s+available\b",
        r"\bno\s+author\s+guidelines?\b",
    ]

    has_heading = _contains_any(text, heading_signals)
    process_count = _count_any(text, process_signals)
    has_negative = _contains_any(text, negative_signals)

    if has_negative and not (has_heading or process_count >= 2):
        return {
            "rule_id": rule_id,
            "result": "fail",
            "confidence": 0.84,
            "notes": "Instructions for authors appear missing or explicitly unavailable.",
            "evidence_urls": evidence_urls,
        }

    if has_heading and process_count >= 2:
        confidence = 0.84 if process_count >= 4 else 0.77
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": confidence,
            "notes": "Instructions for authors are present with manuscript/submission guidance.",
            "evidence_urls": evidence_urls,
        }

    if has_heading:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.62,
            "notes": "Instructions for authors heading is present but detailed guidance is limited.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.55,
        "notes": "Author instruction wording is not explicit enough for automatic decision.",
        "evidence_urls": evidence_urls,
    }


def _optional_not_provided(rule_id: str, rule_hint: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "result": "not_provided",
        "confidence": 1.0,
        "notes": f"Optional URL for `{rule_hint}` was not provided.",
        "evidence_urls": [],
    }


def evaluate_plagiarism_policy(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.plagiarism_policy.v1"
    rule_hint = "plagiarism_policy"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        fallback_pages = _get_policy_pages(submission, "instructions_for_authors")
        if fallback_pages and _contains_any(_text_blob(fallback_pages), [r"\bplagiarism\b", r"\bsimilarity\b"]):
            pages = fallback_pages
    if not pages:
        out = _optional_not_provided(rule_id, rule_hint)
        out["evidence_urls"] = _get_policy_urls(submission, rule_hint)
        return out

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]
    has_policy = _contains_any(text, [r"\bplagiarism\b", r"\bsimilarity index\b", r"\boriginality\b"])
    tools = [
        name
        for name, pattern in {
            "Turnitin": r"\bturnitin\b",
            "iThenticate": r"\bithenticate\b",
            "Crossref Similarity Check": r"\bcrossref similarity check\b",
            "PlagScan": r"\bplagscan\b",
        }.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]

    threshold_match = re.search(r"(maximum|max|below|under)\s+(\d{1,2})\s*%[^.\n]{0,40}(similarity|plagiarism)", text, flags=re.IGNORECASE)
    if threshold_match is None:
        threshold_match = re.search(r"(similarity|plagiarism)[^.\n]{0,40}(\d{1,2})\s*%", text, flags=re.IGNORECASE)
    threshold = threshold_match.group(2) if threshold_match else ""

    if has_policy and tools and threshold:
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": 0.8,
            "notes": f"Plagiarism policy detected with tool(s): {', '.join(tools)} and similarity threshold: {threshold}%.",
            "evidence_urls": evidence_urls,
        }

    if has_policy:
        detail = []
        if not tools:
            detail.append("tool name not found")
        if not threshold:
            detail.append("similarity threshold not found")
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.62,
            "notes": "Plagiarism policy text exists but " + ", ".join(detail) + ".",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.5,
        "notes": "Plagiarism policy URL exists but no clear policy wording was detected.",
        "evidence_urls": evidence_urls,
    }


def evaluate_archiving_policy(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.archiving_policy.v1"
    rule_hint = "archiving_policy"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        out = _optional_not_provided(rule_id, rule_hint)
        out["evidence_urls"] = _get_policy_urls(submission, rule_hint)
        return out

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]
    services = [
        name
        for name, pattern in {
            "CLOCKSS": r"\bclockss\b",
            "LOCKSS": r"\blockss\b",
            "Portico": r"\bportico\b",
            "PKP PN": r"\bpkp\s*pn\b",
            "Internet Archive": r"\binternet archive\b",
            "PubMed Central": r"\bpubmed central\b|\bpmc\b",
            "National Library": r"\bnational library\b",
            "CINES": r"\bcines\b",
        }.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    has_no_archiving = _contains_any(text, [r"\bnot archived\b", r"\bno archiving\b", r"\bno long[- ]term preservation\b"])

    if services:
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": 0.79,
            "notes": f"Archiving policy detected with service(s): {', '.join(services)}.",
            "evidence_urls": evidence_urls,
        }

    if has_no_archiving:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.58,
            "notes": "Archiving policy indicates content is not archived with a long-term preservation service.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.54,
        "notes": "Archiving URL exists but no recognized preservation service was detected.",
        "evidence_urls": evidence_urls,
    }


def evaluate_repository_policy(submission: dict[str, Any]) -> dict[str, Any]:
    rule_id = "doaj.repository_policy.v1"
    rule_hint = "repository_policy"
    pages = _get_policy_pages(submission, rule_hint)
    if not pages:
        out = _optional_not_provided(rule_id, rule_hint)
        out["evidence_urls"] = _get_policy_urls(submission, rule_hint)
        return out

    text = _text_blob(pages)
    evidence_urls = [page["url"] for page in pages]
    has_no_policy = _contains_any(text, [r"\bno repository policy\b", r"\bjournal has no repository policy\b"])
    version_signals = [
        r"\bsubmitted version\b",
        r"\baccepted version\b",
        r"\bauthor accepted manuscript\b",
        r"\bpostprint\b",
        r"\bpreprint\b",
        r"\bpublished version\b",
        r"\bversion of record\b",
    ]
    repository_services = [
        name
        for name, pattern in {
            "Sherpa/Romeo": r"\bsherpa/?romeo\b",
            "Dulcinea": r"\bdulcinea\b",
            "Diadorim": r"\bdiadorim\b",
            "Mir@bel": r"\bmir@?bel\b",
            "Institutional repository": r"\binstitutional repository\b",
        }.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    has_version_statement = _contains_any(text, version_signals)
    has_license = _contains_any(text, list(LICENSE_PATTERNS.values()) + [r"\blicen[sc]e\b"])

    if has_no_policy:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.6,
            "notes": "Repository policy explicitly states no policy is available.",
            "evidence_urls": evidence_urls,
        }

    if has_version_statement and (has_license or repository_services):
        extra = f" Registry/service mention: {', '.join(repository_services)}." if repository_services else ""
        return {
            "rule_id": rule_id,
            "result": "pass",
            "confidence": 0.76,
            "notes": "Repository policy covers version-specific deposit conditions." + extra,
            "evidence_urls": evidence_urls,
        }

    if has_version_statement:
        return {
            "rule_id": rule_id,
            "result": "need_human_review",
            "confidence": 0.6,
            "notes": "Repository policy mentions article versions but license/deposit conditions are unclear.",
            "evidence_urls": evidence_urls,
        }

    return {
        "rule_id": rule_id,
        "result": "need_human_review",
        "confidence": 0.52,
        "notes": "Repository policy URL exists but no clear preprint/postprint/version-of-record policy was detected.",
        "evidence_urls": evidence_urls,
    }
