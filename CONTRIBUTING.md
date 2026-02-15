# Contributing to DOAJ_Reviewer

## Scope

Contributions should improve reviewer quality, reproducibility, and auditability.
This project is for submission review, not automatic submission filling.

## How to Contribute

1. Create an issue describing the problem or proposal.
2. Create a branch from `main`.
3. Add or update tests for behavior changes.
4. Keep changes focused and explain rule impact clearly.
5. Open a pull request with:
   - summary of changes,
   - affected rule IDs,
   - sample input/output evidence.

## Development Checklist

- Run tests locally:
  - `PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py" -v`
- Ensure JSON specs/rules stay valid.
- Avoid destructive git history edits on shared branches.

## Rule Change Guidance

When modifying evaluator logic:

- keep rule IDs stable unless versioning intentionally changes,
- update `specs/reviewer/rules/ruleset.must.v1.json` if required,
- document rationale in PR notes with DOAJ reference links.
