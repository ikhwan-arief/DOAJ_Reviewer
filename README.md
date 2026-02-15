# DOAJ_Reviewer

Online reviewer for DOAJ application submissions.

## Scope

This repository is focused on automated review (not form filling):

- read applicant-provided URLs,
- extract and analyze page text,
- compare findings against DOAJ guidance/rules,
- return `pass`, `fail`, or `need_human_review` with evidence.

## Current specs

- Endogeny rule package:
  - `specs/reviewer/rules/endogeny.v1.yaml`
  - `specs/reviewer/schemas/endogeny-evaluation.schema.json`
  - `specs/reviewer/templates/endogeny-audit-report.md`
  - `specs/reviewer/schemas/submission.schema.json`

## Current implementation

- Python evaluator skeleton for endogeny:
  - `src/doaj_reviewer/basic_rules.py`
  - `src/doaj_reviewer/endogeny.py`
  - `src/doaj_reviewer/intake.py`
  - `src/doaj_reviewer/web.py`
  - `src/doaj_reviewer/evaluate.py`
  - `src/doaj_reviewer/review.py`
  - `src/doaj_reviewer/reporting.py`
  - `src/doaj_reviewer/sim_server.py`
- Example input:
  - `examples/submission.raw.example.json`
  - `examples/submission.example.json`
  - `examples/submissions_batch.template.csv`
- Unit tests:
  - `tests/test_basic_rules.py`
  - `tests/test_endogeny.py`
  - `tests/test_intake.py`
  - `tests/test_review.py`
  - `tests/test_sim_server.py`
  - `tests/test_spreadsheet_batch.py`
  - `tests/test_web.py`
- GitHub Actions:
  - `.github/workflows/ci.yml`
  - `.github/workflows/review-submission.yml`

## Run locally

Raw submission (URL-based intake + evaluation):

```bash
PYTHONPATH=src python -m doaj_reviewer.evaluate \
  --submission examples/submission.raw.example.json \
  --input-mode raw \
  --js-mode auto \
  --structured-output /tmp/submission.structured.json \
  --output-json /tmp/endogeny-result.json \
  --output-md /tmp/endogeny-report.md
```

Structured submission (direct evaluation):

```bash
PYTHONPATH=src python -m doaj_reviewer.evaluate \
  --submission examples/submission.example.json \
  --input-mode structured \
  --output-json /tmp/endogeny-result.json \
  --output-md /tmp/endogeny-report.md
```

Run aggregate reviewer (`must` ruleset summary + endogeny detail):

```bash
PYTHONPATH=src python -m doaj_reviewer.review \
  --submission examples/submission.example.json \
  --summary-json /tmp/review-summary.json \
  --summary-md /tmp/review-summary.md \
  --endogeny-json /tmp/endogeny-result.json \
  --endogeny-md /tmp/endogeny-report.md
```

Batch from spreadsheet CSV:

```bash
PYTHONPATH=src python -m doaj_reviewer.spreadsheet_batch \
  --input-csv examples/submissions_batch.template.csv \
  --output-dir /tmp/doaj-batch \
  --js-mode auto
```

Spreadsheet conversion-only (no crawling/review execution):

```bash
PYTHONPATH=src python -m doaj_reviewer.spreadsheet_batch \
  --input-csv examples/submissions_batch.template.csv \
  --output-dir /tmp/doaj-batch \
  --convert-only
```

Web simulation app (real form -> run -> artifacts):

```bash
PYTHONPATH=src python -m doaj_reviewer.sim_server --host 127.0.0.1 --port 8787
```

Open: `http://127.0.0.1:8787`

Useful simulation endpoints:

- `GET /api/runs` (default latest 20 runs, optional `?limit=all` or `?limit=<n>`)
- `GET /api/export.csv?limit=all` (download aggregated runs overview as CSV)
- `GET /runs/<run_id>/<artifact-file>` (read stored artifact file)

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py" -v
```

## Notes

- Intake crawler supports static HTML parsing and optional JS-render fallback (`--js-mode auto|on`) using Playwright when available.
- If HTTPS certificate verification fails on local Python, fetcher retries once with insecure TLS (skip-verify) so policy pages can still be read.
- Output decisions are `pass`, `fail`, or `need_human_review`.
- Auto-evaluated checks currently include:
  - `doaj.open_access_statement.v1`
  - `doaj.aims_scope.v1`
  - `doaj.editorial_board.v1`
  - `doaj.instructions_for_authors.v1`
  - `doaj.peer_review_policy.v1`
  - `doaj.license_terms.v1`
  - `doaj.copyright_author_rights.v1`
  - `doaj.publication_fees_disclosure.v1`
  - `doaj.publisher_identity.v1`
  - `doaj.issn_consistency.v1`
  - `doaj.endogeny.v1`
- All current `must` checks in `ruleset.must.v1.json` are wired to automatic evaluators.
