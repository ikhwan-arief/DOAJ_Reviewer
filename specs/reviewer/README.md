# Reviewer Specs

This folder contains machine-readable specs for the online reviewer workflow.

## Endogeny rule package

- Rule definition: `rules/endogeny.v1.yaml`
- Must ruleset (aggregate): `rules/ruleset.must.v1.json`
- Output schema: `schemas/endogeny-evaluation.schema.json`
- Human-readable report template: `templates/endogeny-audit-report.md`
- Submission schema: `schemas/submission.schema.json`
- Raw submission schema: `schemas/submission-raw.schema.json`

## Implemented must checks

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

## Intended evaluator flow

1. Crawl and render applicant-provided URLs (JS-capable fetch when needed).
2. Detect publication model:
   - issue-based (evaluate latest 2 issues), or
   - continuous publication (evaluate last calendar year).
3. Build role set:
   - editors,
   - editorial board members,
   - reviewers (if available on the journal site).
4. Collect research articles in each measurement unit.
5. Match article authors against the role set (normalized + fuzzy matching).
6. Compute ratio per unit:
   - numerator: research articles with at least one matched author,
   - denominator: total research articles in the same unit.
7. Decide:
   - `pass` if all measured units are `<= 0.25` and evidence is sufficient,
   - `fail` if any measured unit is `> 0.25`,
   - `need_human_review` if evidence is incomplete/ambiguous.
8. Emit JSON that validates against `schemas/endogeny-evaluation.schema.json`.
9. Render Markdown report using `templates/endogeny-audit-report.md`.

## Notes

- This spec treats endogeny as a `must` requirement.
- For continuous publication, the minimum expected sample is 5 research articles in the last calendar year.
