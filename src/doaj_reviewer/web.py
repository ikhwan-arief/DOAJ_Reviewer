"""Lightweight web fetch and HTML parsing utilities."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = "DOAJ-Reviewer/0.1 (+https://github.com/)"


@dataclass
class ParsedDocument:
    url: str
    status_code: int
    content_type: str
    title: str
    text: str
    links: list[str]
    meta: dict[str, list[str]]
    raw_html: str


class _HTMLCollector(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self.meta: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        tag_l = tag.lower()

        if tag_l in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag_l == "title":
            self._in_title = True
            return
        if tag_l == "br":
            self.text_parts.append("\n")
            return
        if tag_l in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text_parts.append("\n")

        if tag_l == "a":
            href = attrs_dict.get("href", "").strip()
            if href:
                self.links.append(urljoin(self.base_url, href))
            return

        if tag_l == "meta":
            key = (
                attrs_dict.get("name", "")
                or attrs_dict.get("property", "")
                or attrs_dict.get("http-equiv", "")
            ).strip().lower()
            value = attrs_dict.get("content", "").strip()
            if key and value:
                self.meta.setdefault(key, []).append(value)

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l in {"script", "style", "noscript"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag_l == "title":
            self._in_title = False
            return
        if tag_l in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)


def _decode_body(body: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([^\s;]+)", content_type or "", re.IGNORECASE)
    if charset_match:
        encoding = charset_match.group(1).strip("\"' ")
        try:
            return body.decode(encoding, errors="replace")
        except LookupError:
            pass
    for fallback in ("utf-8", "latin-1"):
        try:
            return body.decode(fallback, errors="replace")
        except Exception:
            continue
    return body.decode("utf-8", errors="replace")


def _response_to_tuple(response, max_bytes: int) -> tuple[int, str, str]:
    status_code = int(getattr(response, "status", 200))
    content_type = str(response.headers.get("Content-Type", ""))
    body = response.read(max_bytes)
    return status_code, content_type, _decode_body(body, content_type)


def _is_cert_verification_error(exc: Exception) -> bool:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            return True
        if isinstance(reason, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(reason):
            return True
    text = str(exc).lower()
    return "certificate verify failed" in text or "unable to get local issuer certificate" in text


def fetch_url(url: str, timeout_seconds: int = 20, max_bytes: int = 2_000_000) -> tuple[int, str, str]:
    req = Request(url=url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            return _response_to_tuple(response, max_bytes=max_bytes)
    except HTTPError as exc:
        content_type = str(exc.headers.get("Content-Type", ""))
        body = exc.read(max_bytes)
        return int(exc.code), content_type, _decode_body(body, content_type)
    except Exception as exc:
        if not _is_cert_verification_error(exc):
            raise

        insecure_context = ssl._create_unverified_context()
        try:
            with urlopen(req, timeout=timeout_seconds, context=insecure_context) as response:
                status_code, content_type, html = _response_to_tuple(response, max_bytes=max_bytes)
                if content_type:
                    content_type = f"{content_type}; tls=insecure-no-verify"
                else:
                    content_type = "text/html; tls=insecure-no-verify"
                return status_code, content_type, html
        except HTTPError as insecure_exc:
            content_type = str(insecure_exc.headers.get("Content-Type", ""))
            body = insecure_exc.read(max_bytes)
            if content_type:
                content_type = f"{content_type}; tls=insecure-no-verify"
            else:
                content_type = "text/html; tls=insecure-no-verify"
            return int(insecure_exc.code), content_type, _decode_body(body, content_type)


def fetch_url_playwright(url: str, timeout_seconds: int = 20) -> tuple[int, str, str]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Playwright is not available in this environment.") from exc

    with sync_playwright() as playwright:  # pragma: no cover - environment dependent
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DEFAULT_USER_AGENT)
        page = context.new_page()
        response = page.goto(url, wait_until="networkidle", timeout=max(1, timeout_seconds) * 1000)
        html = page.content()
        status_code = int(response.status) if response else 200
        content_type = "text/html; renderer=playwright"
        page.close()
        context.close()
        browser.close()
    return status_code, content_type, html


def parse_html(url: str, status_code: int, content_type: str, html: str) -> ParsedDocument:
    parser = _HTMLCollector(url)
    parser.feed(html)
    parser.close()

    title = unescape(" ".join(parser.title_parts)).strip()
    text = unescape(" ".join(parser.text_parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    links: list[str] = []
    seen = set()
    for link in parser.links:
        link = link.strip()
        if not link or link in seen:
            continue
        seen.add(link)
        links.append(link)

    return ParsedDocument(
        url=url,
        status_code=status_code,
        content_type=content_type,
        title=title,
        text=text,
        links=links,
        meta=parser.meta,
        raw_html=html,
    )


def fetch_parsed_document(url: str, timeout_seconds: int = 20) -> ParsedDocument:
    status_code, content_type, html = fetch_url(url=url, timeout_seconds=timeout_seconds)
    return parse_html(url=url, status_code=status_code, content_type=content_type, html=html)


def fetch_parsed_document_playwright(url: str, timeout_seconds: int = 20) -> ParsedDocument:
    status_code, content_type, html = fetch_url_playwright(url=url, timeout_seconds=timeout_seconds)
    return parse_html(url=url, status_code=status_code, content_type=content_type, html=html)


def detect_waf_challenge(doc: ParsedDocument) -> dict[str, Any]:
    blob = f"{doc.title}\n{doc.text[:5000]}\n{doc.raw_html[:15000]}".lower()
    status_suspicious = doc.status_code in {401, 403, 406, 409, 429, 503}

    provider = ""
    if any(token in blob for token in ["cloudflare", "__cf_chl_", "cf-ray", "cf-chl", "just a moment..."]):
        provider = "cloudflare"
    elif any(token in blob for token in ["akamai", "akamai ghost", "akamaibot"]):
        provider = "akamai"
    elif any(token in blob for token in ["imperva", "incapsula"]):
        provider = "imperva"
    elif any(token in blob for token in ["sucuri", "sucuri website firewall"]):
        provider = "sucuri"
    elif any(token in blob for token in ["web application firewall", "waf", "ddos protection"]):
        provider = "generic_waf"

    strong_markers = [
        "checking your browser before accessing",
        "attention required!",
        "verify you are human",
        "please enable cookies",
        "captcha",
        "turnstile",
        "security check",
        "request blocked",
        "access denied",
        "automated queries",
        "bot protection",
        "challenge platform",
    ]
    generic_markers = [
        "forbidden",
        "temporarily unavailable",
        "rate limited",
        "too many requests",
        "blocked",
        "challenge",
    ]

    matched_strong = [token for token in strong_markers if token in blob]
    matched_generic = [token for token in generic_markers if token in blob]
    marker_count = len(matched_strong) + len(matched_generic)
    is_short_shell = len(doc.text.strip()) < 700

    blocked = False
    if matched_strong and (status_suspicious or is_short_shell or provider):
        blocked = True
    elif provider and marker_count >= 2 and (status_suspicious or is_short_shell):
        blocked = True
    elif status_suspicious and marker_count >= 3:
        blocked = True

    reason = ""
    if matched_strong:
        reason = matched_strong[0]
    elif matched_generic:
        reason = matched_generic[0]

    return {
        "blocked": blocked,
        "provider": provider,
        "reason": reason,
    }


def needs_js_render(doc: ParsedDocument) -> bool:
    html_l = doc.raw_html.lower()
    text_len = len(doc.text.strip())
    line_count = len([line for line in doc.text.splitlines() if line.strip()])
    script_count = html_l.count("<script")
    has_root_mount = any(token in html_l for token in ['id="app"', "id='app'", 'id="root"', "id='root'"])
    has_js_hint = any(
        hint in html_l
        for hint in [
            "enable javascript",
            "javascript is required",
            "noscript",
            "__next",
            "data-reactroot",
        ]
    )
    has_citation_meta = any(key.startswith("citation_") for key in doc.meta.keys())

    if has_citation_meta:
        return False
    if has_js_hint and text_len < 300:
        return True
    if has_root_mount and script_count >= 2 and text_len < 500:
        return True
    if script_count >= 4 and line_count <= 5 and text_len < 220:
        return True
    return False


def fetch_parsed_document_with_fallback(
    url: str,
    timeout_seconds: int = 20,
    js_mode: str = "auto",
) -> ParsedDocument:
    mode = (js_mode or "auto").lower().strip()
    if mode not in {"off", "auto", "on"}:
        raise ValueError("js_mode must be one of: off, auto, on")

    if mode == "off":
        return fetch_parsed_document(url=url, timeout_seconds=timeout_seconds)

    if mode == "on":
        return fetch_parsed_document_playwright(url=url, timeout_seconds=timeout_seconds)

    try:
        static_doc = fetch_parsed_document(url=url, timeout_seconds=timeout_seconds)
    except Exception as static_exc:
        try:
            return fetch_parsed_document_playwright(url=url, timeout_seconds=timeout_seconds)
        except Exception:
            raise static_exc

    if static_doc.status_code >= 400:
        try:
            dynamic_doc = fetch_parsed_document_playwright(url=url, timeout_seconds=timeout_seconds)
            static_len = len(static_doc.text.strip())
            dynamic_len = len(dynamic_doc.text.strip())
            if dynamic_doc.status_code < static_doc.status_code or dynamic_len > static_len + 100:
                return dynamic_doc
        except Exception:
            return static_doc
        return static_doc

    if not needs_js_render(static_doc):
        return static_doc

    try:
        return fetch_parsed_document_playwright(url=url, timeout_seconds=timeout_seconds)
    except Exception:
        return static_doc


def same_domain(url_a: str, url_b: str) -> bool:
    host_a = (urlparse(url_a).netloc or "").lower()
    host_b = (urlparse(url_b).netloc or "").lower()
    if not host_a or not host_b:
        return False
    if host_a == host_b:
        return True
    return host_a.endswith("." + host_b) or host_b.endswith("." + host_a)


def url_path(url: str) -> str:
    return (urlparse(url).path or "").lower()


def flatten_meta_values(meta: dict[str, list[str]], keys: list[str]) -> list[str]:
    values: list[str] = []
    for key in keys:
        for value in meta.get(key.lower(), []):
            if value and value not in values:
                values.append(value)
    return values


def safe_excerpt(text: str, limit: int = 300) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def top_lines(text: str, limit: int = 8) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[:limit]


def summarize_document(doc: ParsedDocument) -> dict[str, Any]:
    return {
        "url": doc.url,
        "status_code": doc.status_code,
        "title": doc.title,
        "content_type": doc.content_type,
        "line_count": len([line for line in doc.text.splitlines() if line.strip()]),
        "link_count": len(doc.links),
    }
