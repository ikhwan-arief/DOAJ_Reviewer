from __future__ import annotations

import unittest
from unittest.mock import patch

from doaj_reviewer.web import (
    ParsedDocument,
    detect_waf_challenge,
    fetch_parsed_document_with_fallback,
    needs_js_render,
    parse_html,
)


class WebHeuristicTests(unittest.TestCase):
    def test_needs_js_render_true_for_script_heavy_shell(self) -> None:
        html = """
        <html>
          <head><title>App Shell</title></head>
          <body>
            <div id="app"></div>
            <script src="/static/a.js"></script>
            <script src="/static/b.js"></script>
            <script src="/static/c.js"></script>
            <noscript>Please enable JavaScript.</noscript>
          </body>
        </html>
        """
        doc = parse_html(
            url="https://example.org",
            status_code=200,
            content_type="text/html",
            html=html,
        )
        self.assertTrue(needs_js_render(doc))

    def test_needs_js_render_false_for_citation_meta_page(self) -> None:
        html = """
        <html>
          <head>
            <title>Article</title>
            <meta name="citation_title" content="Sample Article"/>
            <meta name="citation_author" content="Jane Doe"/>
          </head>
          <body>
            <h1>Sample Article</h1>
            <p>Plain text content.</p>
          </body>
        </html>
        """
        doc = parse_html(
            url="https://example.org/article/1",
            status_code=200,
            content_type="text/html",
            html=html,
        )
        self.assertFalse(needs_js_render(doc))

    def test_auto_mode_uses_playwright_when_static_fetch_fails(self) -> None:
        dynamic = ParsedDocument(
            url="https://example.org/policy",
            status_code=200,
            content_type="text/html; renderer=playwright",
            title="Policy",
            text="Open access policy text with license terms.",
            links=[],
            meta={},
            raw_html="<html></html>",
        )
        with patch("doaj_reviewer.web.fetch_parsed_document", side_effect=RuntimeError("static failed")):
            with patch("doaj_reviewer.web.fetch_parsed_document_playwright", return_value=dynamic):
                doc = fetch_parsed_document_with_fallback(
                    url="https://example.org/policy",
                    timeout_seconds=20,
                    js_mode="auto",
                )
        self.assertEqual(doc.title, "Policy")
        self.assertEqual(doc.status_code, 200)

    def test_auto_mode_prefers_playwright_for_http_error_static_doc(self) -> None:
        static_doc = ParsedDocument(
            url="https://example.org/policy",
            status_code=403,
            content_type="text/html",
            title="Forbidden",
            text="Access denied",
            links=[],
            meta={},
            raw_html="<html><body>Access denied</body></html>",
        )
        dynamic_doc = ParsedDocument(
            url="https://example.org/policy",
            status_code=200,
            content_type="text/html; renderer=playwright",
            title="Policy Page",
            text="Peer review policy and editorial process with open access license details.",
            links=[],
            meta={},
            raw_html="<html><body>Policy Page</body></html>",
        )
        with patch("doaj_reviewer.web.fetch_parsed_document", return_value=static_doc):
            with patch("doaj_reviewer.web.fetch_parsed_document_playwright", return_value=dynamic_doc):
                doc = fetch_parsed_document_with_fallback(
                    url="https://example.org/policy",
                    timeout_seconds=20,
                    js_mode="auto",
                )
        self.assertEqual(doc.status_code, 200)
        self.assertEqual(doc.title, "Policy Page")

    def test_detect_waf_cloudflare_challenge(self) -> None:
        html = """
        <html>
          <head><title>Just a moment...</title></head>
          <body>
            <h1>Checking your browser before accessing example.org</h1>
            <p>Please enable JavaScript and Cookies.</p>
            <div>Ray ID: 8abced1234</div>
          </body>
        </html>
        """
        doc = parse_html(
            url="https://example.org/policy",
            status_code=503,
            content_type="text/html",
            html=html,
        )
        detection = detect_waf_challenge(doc)
        self.assertTrue(detection["blocked"])
        self.assertEqual(detection["provider"], "cloudflare")

    def test_detect_waf_false_for_normal_policy_page(self) -> None:
        html = """
        <html>
          <head><title>Open Access Policy</title></head>
          <body>
            <h1>Open Access Policy</h1>
            <p>All articles are available without charge and distributed under CC BY.</p>
            <p>The policy also explains usage rights and archiving routes.</p>
          </body>
        </html>
        """
        doc = parse_html(
            url="https://example.org/open-access",
            status_code=200,
            content_type="text/html",
            html=html,
        )
        detection = detect_waf_challenge(doc)
        self.assertFalse(detection["blocked"])


if __name__ == "__main__":
    unittest.main()
