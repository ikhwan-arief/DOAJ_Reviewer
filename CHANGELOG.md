# Changelog

All notable updates to this repository are listed here.

## 2026-02-16

- Added WAF/anti-bot challenge detection (Cloudflare/Akamai/Imperva/Sucuri/generic patterns) in the crawler.
- Added explicit `need_human_review` notes when policy pages are blocked by WAF.
- Added per-domain throttling and exponential retry in intake crawling.
- Added manual policy text input per rule in simulation UI for blocked URLs.
- Added optional manual PDF upload per rule in simulation UI.
- Server-side PDF text extraction (best effort using `pypdf` / `PyPDF2` when available).
- Added warnings for invalid/unreadable manual PDF uploads.
- Added `Print to PDF` button (browser print flow, user selects folder).
- Added `Download text` button (`.txt` plain text summary).
- Added `review-summary.txt` artifact generation in run output.
- Added plain text review summary renderer for CLI and simulation artifacts.
- Added tests for WAF detection and non-WAF page handling.
- Added tests for WAF + manual fallback flow in intake.
- Added tests for manual fallback payload normalization and warnings.
- Added tests for text summary rendering and `.txt` artifact generation.
- Added reset button for simulation form.
- Updated English UI labels and field order aligned with DOAJ-oriented flow.
- Enforced reviewer composition separately from editorial board composition.
- Treated editorial board composition as informational (no hard threshold).
- Aligned endogeny and must/non-must handling with discussed requirements.

## 2026-02-15

- Added English step-by-step Codespaces usage guide for non-technical collaborators.
- Updated repository metadata and support pages (`CONTRIBUTING.md`, `SUPPORT.md`, repository About details).
