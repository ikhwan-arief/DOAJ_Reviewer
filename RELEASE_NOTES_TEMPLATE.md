# Release Notes Template

Use this template when publishing a new GitHub release for each version/tag.

## Release Information

- Version/Tag: `vX.Y.Z`
- Release Date (UTC): `YYYY-MM-DD`
- Branch: `main`
- Commit: `<short-sha>`
- Summary: `<one-sentence release summary>`

## Highlights

1. `<highlight 1>`
2. `<highlight 2>`
3. `<highlight 3>`

## Added

- `<new feature>`
- `<new capability>`

## Changed

- `<behavior change>`
- `<refactor or update>`

## Fixed

- `<bug fix>`
- `<stability/performance fix>`

## Breaking Changes

- `None` or `<breaking change + impact>`

## Migration Notes

- `None` or `<what users must do after upgrade>`

## Validation

- Test command: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`
- Result: `<for example: 37 passed>`

## Artifacts

- `<link to changelog section>`
- `<link to important docs>`
- `<link to demo/simulation instructions>`

## Known Limitations

- `<limitation 1>`
- `<limitation 2>`

