# DOAJ_Reviewer

[![CI](https://github.com/ikhwan-arief/DOAJ_Reviewer/actions/workflows/ci.yml/badge.svg)](https://github.com/ikhwan-arief/DOAJ_Reviewer/actions/workflows/ci.yml)

Automated reviewer for DOAJ application submissions.

## About

This project validates applicant-provided journal URLs against DOAJ must-rules.
It is designed as a reviewer assistant, not a form-filling assistant.

Main objective:

- crawl journal policy/content pages from submission URLs,
- extract natural-language text and structured signals,
- evaluate rules and provide decision outputs with evidence,
- route uncertain cases to human review.

Primary DOAJ references used by this repository:

- https://doaj.org/apply/
- https://doaj.org/apply/guide/
- https://doaj.org/apply/transparency/
- https://doaj.org/apply/copyright-and-licensing/

## Latest Updates (February 16, 2026)

- WAF/Cloudflare-aware crawling: blocked pages are detected and routed to `need_human_review`.
- Per-domain throttling + exponential retry were added to reduce rate-limit/block failures.
- Manual fallback for blocked policy URLs: paste policy text and optionally upload policy PDF in simulation UI.
- `Print to PDF` from browser print dialog (user chooses save location).
- `Download text` for plain-text summary (`.txt`).
- Run artifacts now include `review-summary.txt`.
- Reviewer policy checks were refined for DOAJ-oriented field order and reviewer composition rules.

See full history in `CHANGELOG.md`.

## Decision Outputs

Each rule check returns one of:

- `pass`
- `fail`
- `need_human_review`

The aggregate decision in `review-summary.json` follows:

- any `fail` -> overall `fail`
- otherwise, any `need_human_review` -> overall `need_human_review`
- otherwise -> overall `pass`

## Rule Coverage

Current automatic evaluators:

- `doaj.open_access_statement.v1`
- `doaj.issn_consistency.v1`
- `doaj.publisher_identity.v1`
- `doaj.license_terms.v1`
- `doaj.copyright_author_rights.v1`
- `doaj.peer_review_policy.v1`
- `doaj.aims_scope.v1`
- `doaj.editorial_board.v1`
- `doaj.instructions_for_authors.v1`
- `doaj.publication_fees_disclosure.v1`
- `doaj.endogeny.v1`

Supplementary (non-must) checks:

- `doaj.plagiarism_policy.v1`
- `doaj.archiving_policy.v1`
- `doaj.repository_policy.v1`

Endogeny rule follows DOAJ threshold logic:

- issue-based journals: max 25% in each of the latest two issues
- continuous model: max 25% in last calendar year, minimum 5 articles

## Repository Structure

- Core logic: `src/doaj_reviewer/`
- Rule/spec docs: `specs/reviewer/`
- Examples: `examples/`
- Tests: `tests/`
- CI/workflows: `.github/workflows/`

## Local Usage

Run all tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py" -v
```

Run structured submission review:

```bash
PYTHONPATH=src python -m doaj_reviewer.review \
  --submission examples/submission.example.json \
  --summary-json /tmp/review-summary.json \
  --summary-md /tmp/review-summary.md \
  --endogeny-json /tmp/endogeny-result.json \
  --endogeny-md /tmp/endogeny-report.md
```

Run raw URL submission intake + review:

```bash
PYTHONPATH=src python -m doaj_reviewer.evaluate \
  --submission examples/submission.raw.example.json \
  --input-mode raw \
  --js-mode auto \
  --structured-output /tmp/submission.structured.json \
  --output-json /tmp/endogeny-result.json \
  --output-md /tmp/endogeny-report.md
```

Run spreadsheet batch:

```bash
PYTHONPATH=src python -m doaj_reviewer.spreadsheet_batch \
  --input-csv examples/submissions_batch.template.csv \
  --output-dir /tmp/doaj-batch \
  --js-mode auto
```

Convert spreadsheet rows to raw JSON only (without crawling):

```bash
PYTHONPATH=src python -m doaj_reviewer.spreadsheet_batch \
  --input-csv examples/submissions_batch.template.csv \
  --output-dir /tmp/doaj-batch \
  --convert-only
```

## Simulation Web App

Start local simulation server:

```bash
PYTHONPATH=src python -m doaj_reviewer.sim_server --host 127.0.0.1 --port 8787
```

Open:

- `http://127.0.0.1:8787`
- `Print to PDF` (browser print dialog, user chooses Save as PDF + target folder)
- `Download text` (plain `.txt` summary file for current simulation result)

Useful endpoints:

- `GET /api/runs` (default latest 20, supports `?limit=all` or `?limit=<n>`)
- `GET /api/export.csv?limit=all` (download all runs summary as CSV)
- `GET /runs/<run_id>/<artifact-file>` (download run artifacts)

## GitHub Actions

This repository includes:

- `CI` workflow on push/pull_request (`.github/workflows/ci.yml`)
- manual review workflow (`.github/workflows/review-submission.yml`)

Manual workflow can process a submission file from the repository and upload:

- `review-summary.json` / `review-summary.md`
- `endogeny-result.json` / `endogeny-report.md`
- `submission.structured.json`

## Notes and Limitations

- Current implementation is deterministic rule-based evaluation (heuristic NLP + regex patterns), without external LLM APIs.
- JS-heavy pages are supported via Playwright (`js_mode=auto|on`) when Playwright is installed.
- WAF/anti-bot challenge pages (Cloudflare/Akamai/etc.) are detected and routed to `need_human_review` with explicit notes.
- Intake applies per-domain throttling and exponential retries to reduce blocking/rate-limit failures.
- Simulation UI includes manual fallback: paste policy text and optional per-policy PDF upload when URL crawling is blocked.
- If Python TLS verification fails locally, fetcher retries once using insecure TLS (skip-verify).
- Some journals may still require manual review due to anti-bot controls, auth walls, or ambiguous policy wording.

## Repository Information

- Change log: `CHANGELOG.md`
- Release notes template: `RELEASE_NOTES_TEMPLATE.md`
- Contribution guide: `CONTRIBUTING.md`
- Support guide: `SUPPORT.md`
- Codespaces guide (English): `CODESPACES_GUIDE_EN.md`
