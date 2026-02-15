# Endogeny Audit Report

- Submission ID: `{{submission_id}}`
- Rule ID: `doaj.endogeny.v1`
- Decision: `{{result}}` (`pass` | `fail` | `need_human_review`)
- Confidence: `{{confidence}}`
- Crawl timestamp (UTC): `{{crawl_timestamp_utc}}`

## Summary (English)
{{explanation_en}}

## Publication Model Detection
- Detected model: `{{publication_model}}`
- Detection rationale:
  - {{publication_model_reason_1}}
  - {{publication_model_reason_2}}

## Measurement Window
- If `issue_based`: latest two issues found:
  - `{{unit_1_label}}` (`{{unit_1_url}}`)
  - `{{unit_2_label}}` (`{{unit_2_url}}`)
- If `continuous`: calendar year evaluated:
  - `{{calendar_year}}`

## Metrics
| Unit | Research articles (denominator) | Matched articles (numerator) | Ratio | Threshold |
|---|---:|---:|---:|---:|
| {{metric_row_1_unit}} | {{metric_row_1_denom}} | {{metric_row_1_num}} | {{metric_row_1_ratio}} | 0.25 |
| {{metric_row_2_unit}} | {{metric_row_2_denom}} | {{metric_row_2_num}} | {{metric_row_2_ratio}} | 0.25 |

- Max ratio observed: `{{max_ratio_observed}}`
- All units within threshold: `{{all_units_within_threshold}}`

## Matched Articles (Author vs Role Set)
| Unit | Article title | Article URL | Matched author | Matched role | Matched person | Match method | Match score |
|---|---|---|---|---|---|---|---:|
| {{match_1_unit}} | {{match_1_title}} | {{match_1_article_url}} | {{match_1_author}} | {{match_1_role}} | {{match_1_person}} | {{match_1_method}} | {{match_1_score}} |
| {{match_2_unit}} | {{match_2_title}} | {{match_2_article_url}} | {{match_2_author}} | {{match_2_role}} | {{match_2_person}} | {{match_2_method}} | {{match_2_score}} |

## Sources and Evidence
| Kind | URL | Excerpt (<=300 chars) | Locator hint |
|---|---|---|---|
| {{evidence_1_kind}} | {{evidence_1_url}} | {{evidence_1_excerpt}} | {{evidence_1_locator}} |
| {{evidence_2_kind}} | {{evidence_2_url}} | {{evidence_2_excerpt}} | {{evidence_2_locator}} |

## Missing Data / Limitations
- {{limitation_1}}
- {{limitation_2}}

## Decision Rationale
- `pass`: all measured units are `<= 0.25` with sufficient evidence.
- `fail`: one or more measured units are `> 0.25`.
- `need_human_review`: evidence is incomplete or ambiguous.

## DOAJ References
- https://doaj.org/apply/
- https://doaj.org/apply/guide/
- https://doaj.org/apply/transparency/
- https://doaj.org/apply/copyright-and-licensing/
