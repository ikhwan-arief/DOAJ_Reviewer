from __future__ import annotations

import unittest

from doaj_reviewer.intake import (
    build_structured_submission_from_raw,
    extract_article_from_document,
    extract_role_people_from_document,
)
from doaj_reviewer.web import parse_html


def _doc(url: str, html: str):
    return parse_html(url=url, status_code=200, content_type="text/html; charset=utf-8", html=html)


class IntakeTests(unittest.TestCase):
    def test_extract_role_people_from_document(self) -> None:
        html = """
        <html><body>
        <h2>Editorial Board</h2>
        <p>Editor in Chief: Dr. Jane Smith</p>
        <ul>
          <li>Asep Rahman</li>
          <li>Lina Putri</li>
        </ul>
        </body></html>
        """
        doc = _doc("https://journal.example/editorial-board", html)
        people = extract_role_people_from_document(doc, default_role="editorial_board_member")
        names = {item["name"] for item in people}
        roles_by_name = {item["name"]: item["role"] for item in people}

        self.assertIn("Jane Smith", names)
        self.assertIn("Asep Rahman", names)
        self.assertEqual(roles_by_name["Jane Smith"], "editor")

    def test_extract_article_from_document(self) -> None:
        html = """
        <html><head>
          <meta name="citation_title" content="A Sample Research Article" />
          <meta name="citation_author" content="Jane Smith" />
          <meta name="citation_author" content="Budi Santoso" />
          <meta name="citation_article_type" content="Research Article" />
          <meta name="citation_publication_date" content="2025-06-01" />
        </head><body>test</body></html>
        """
        doc = _doc("https://journal.example/article/view/1", html)
        article = extract_article_from_document(doc)
        assert article is not None
        self.assertEqual(article["title"], "A Sample Research Article")
        self.assertEqual(article["authors"], ["Jane Smith", "Budi Santoso"])
        self.assertEqual(article["article_type"], "Research Article")

    def test_build_structured_submission_from_raw(self) -> None:
        pages = {
            "https://journal.example/editorial-board": """
            <html><body>
              <h2>Editorial Board</h2>
              <p>Editor in Chief: Jane Smith</p>
              <li>Asep Rahman</li>
            </body></html>
            """,
            "https://journal.example/reviewers": """
            <html><body>
              <h2>Reviewers</h2>
              <li>Lina Putri</li>
            </body></html>
            """,
            "https://journal.example/issue-2": """
            <html><body>
              <a href="/article/view/1">Article 1</a>
              <a href="/article/view/2">Article 2</a>
            </body></html>
            """,
            "https://journal.example/issue-1": """
            <html><body>
              <a href="/article/view/3">Article 3</a>
            </body></html>
            """,
            "https://journal.example/article/view/1": """
            <html><head>
              <meta name="citation_title" content="Research A" />
              <meta name="citation_author" content="Jane Smith" />
              <meta name="citation_publication_date" content="2025-01-10" />
            </head></html>
            """,
            "https://journal.example/article/view/2": """
            <html><head>
              <meta name="citation_title" content="Research B" />
              <meta name="citation_author" content="Author B" />
              <meta name="citation_publication_date" content="2025-01-11" />
            </head></html>
            """,
            "https://journal.example/article/view/3": """
            <html><head>
              <meta name="citation_title" content="Research C" />
              <meta name="citation_author" content="Author C" />
              <meta name="citation_publication_date" content="2025-01-12" />
            </head></html>
            """,
            "https://journal.example/open-access": """
            <html><body>
              <h1>Open Access Policy</h1>
              <p>This is an open access journal. Users can read, download, copy, and distribute articles.</p>
            </body></html>
            """,
            "https://journal.example/peer-review": """
            <html><body>
              <h1>Peer Review Policy</h1>
              <p>All manuscripts are peer reviewed by two external reviewers.</p>
            </body></html>
            """,
            "https://journal.example/licensing": """
            <html><body>
              <h1>Licensing</h1>
              <p>Articles use Creative Commons CC BY 4.0 license terms.</p>
            </body></html>
            """,
            "https://journal.example/copyright": """
            <html><body>
              <h1>Copyright Policy</h1>
              <p>Authors retain copyright and grant a non-exclusive publishing license to the journal.</p>
            </body></html>
            """,
            "https://journal.example/apc": """
            <html><body>
              <h1>Publication Fees</h1>
              <p>The journal charges an APC of USD 100 per accepted article.</p>
            </body></html>
            """,
            "https://journal.example/publisher": """
            <html><body>
              <h1>Publisher</h1>
              <p>Publisher: Journal University Press</p>
              <p>Contact: editor@journal.example</p>
              <p>Address: 10 Main Street, City, Country</p>
            </body></html>
            """,
            "https://journal.example/about": """
            <html><body>
              <h1>About</h1>
              <p>ISSN (Print): 1234-5679</p>
              <p>E-ISSN: 2049-3630</p>
            </body></html>
            """,
            "https://journal.example/aims-and-scope": """
            <html><body>
              <h1>Aims and Scope</h1>
              <p>The journal publishes research articles in data science and software engineering.</p>
            </body></html>
            """,
            "https://journal.example/instructions": """
            <html><body>
              <h1>Instructions for Authors</h1>
              <p>Submission guidelines include manuscript format, references, template, and ethics statements.</p>
            </body></html>
            """,
        }

        def fake_fetcher(url: str, timeout_seconds: int = 18):
            _ = timeout_seconds
            if url not in pages:
                raise RuntimeError(f"missing fixture for {url}")
            return _doc(url, pages[url])

        raw_submission = {
            "submission_id": "RAW-1",
            "journal_homepage_url": "https://journal.example",
            "publication_model": "issue_based",
            "source_urls": {
                "editorial_board": ["https://journal.example/editorial-board"],
                "reviewers": ["https://journal.example/reviewers"],
                "latest_content": ["https://journal.example/issue-2", "https://journal.example/issue-1"],
                "archives": [],
                "open_access_statement": ["https://journal.example/open-access"],
                "peer_review_policy": ["https://journal.example/peer-review"],
                "license_terms": ["https://journal.example/licensing"],
                "copyright_author_rights": ["https://journal.example/copyright"],
                "publication_fees_disclosure": ["https://journal.example/apc"],
                "publisher_identity": ["https://journal.example/publisher"],
                "issn_consistency": ["https://journal.example/about"],
                "aims_scope": ["https://journal.example/aims-and-scope"],
                "instructions_for_authors": ["https://journal.example/instructions"],
            },
        }

        structured = build_structured_submission_from_raw(raw_submission, fetcher=fake_fetcher)

        self.assertEqual(structured["submission_id"], "RAW-1")
        self.assertEqual(len(structured["units"]), 2)
        self.assertGreaterEqual(len(structured["role_people"]), 2)
        total_articles = sum(len(unit["research_articles"]) for unit in structured["units"])
        self.assertEqual(total_articles, 3)
        self.assertEqual(len(structured["policy_pages"]), 10)

    def test_manual_policy_text_used_when_waf_blocks_url(self) -> None:
        waf_doc = parse_html(
            url="https://journal.example/open-access",
            status_code=503,
            content_type="text/html",
            html="""
            <html><head><title>Just a moment...</title></head>
            <body>
              <h1>Checking your browser before accessing</h1>
              <p>Cloudflare</p>
            </body></html>
            """,
        )

        def fake_fetcher(url: str, timeout_seconds: int = 18):
            _ = timeout_seconds
            if url == "https://journal.example/open-access":
                return waf_doc
            raise RuntimeError(f"missing fixture for {url}")

        raw_submission = {
            "submission_id": "RAW-WAF",
            "journal_homepage_url": "https://journal.example",
            "publication_model": "issue_based",
            "source_urls": {
                "open_access_statement": ["https://journal.example/open-access"],
                "latest_content": [],
                "editorial_board": [],
                "reviewers": [],
                "archives": [],
            },
            "manual_policy_pages": [
                {
                    "rule_hint": "open_access_statement",
                    "url": "manual://open_access_statement/text",
                    "title": "Manual OA",
                    "text": "This journal is open access and allows reading and reuse under CC BY.",
                }
            ],
        }

        structured = build_structured_submission_from_raw(raw_submission, fetcher=fake_fetcher)
        self.assertTrue(
            any(
                page.get("rule_hint") == "open_access_statement"
                and str(page.get("url", "")).startswith("manual://open_access_statement")
                for page in structured["policy_pages"]
            )
        )
        self.assertTrue(
            any(
                item.get("locator_hint") == "policy-waf-blocked-open_access_statement"
                for item in structured["evidence"]
                if isinstance(item, dict)
            )
        )


if __name__ == "__main__":
    unittest.main()
