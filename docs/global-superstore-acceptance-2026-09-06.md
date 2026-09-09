# Global Superstore real-provider acceptance

## Verdict

The evidence-first report path completed with the configured DeepSeek provider against the imported
Global Superstore file. The source remained unchanged, every numeric claim passed the server-owned
claim checks, and the generated DOCX passed a seven-page visual inspection.

This is an engineering acceptance, not a final business sign-off. Both date fields in the imported
dataset are invalid (`00:00.0` for all 51,290 rows), so the system correctly omitted a time trend
rather than inventing one. Currency is also not declared by the source and must be confirmed before
external delivery.

## Reproducible inputs

- Dataset: Global Superstore, 51,290 rows
- Source SHA-256: `993a3b8bce4a3228c9a9392a5d6296a0d8d964ff6abfecc89e04d59c71b12b0f`
- Provider/model: DeepSeek / `deepseek-v4-flash`
- Execution policy: safe mode, fixed read-only follow-up tools, maximum three rounds
- Acceptance script: `scripts/accept-real-report.py`

## Output and quality

- 7 charts, 7 findings, 13 evidence items, including 3 result-driven evidence items
- Quality score: 84; unverified numeric claims: 0
- Verified totals: sales 12,642,905.00; profit 1,467,457.29; margin 11.61%
- Follow-up decomposition: APAC profit 436,000.05; Technology profit 663,778.73;
  Copiers profit 258,567.55
- Discount/profit correlation: -0.3165; 9,860 high-discount loss records
- Final DOCX SHA-256: `E51A73EF12C9E429254B44EB4923A1E37615F64CC7C92BA411E8F32E35474ED6`

## Model usage

| Stage | Purpose | Tokens | Estimated CNY |
| --- | --- | ---: | ---: |
| Planning | Analysis plan | 3,788 | 0.00268064 |
| Planning | Follow-up analysis 1 | 942 | 0.00099600 |
| Planning | Follow-up analysis 2 | 1,013 | 0.00106700 |
| Planning | Follow-up analysis 3 | 1,089 | 0.00064824 |
| Report | Content review | 2,200 | 0.00269600 |
| **Total** | **5 calls** | **9,032** | **0.00808788** |

The cost is an estimate calculated from the provider pricing configured in the application. The
report body is deterministically assembled from computed evidence; the model created the plan,
selected bounded follow-up computations, and reviewed the content. It did not get permission to
invent or directly overwrite numeric results.

## Document inspection

The canonical LibreOffice renderer was attempted first and was unavailable on this machine. A hidden
local Microsoft Word export produced the PDF, and bundled Poppler rendered all seven pages to PNG.
Each final page was inspected for clipping, overlaps, broken glyphs, chart legibility, repeated table
headers, and appendix pagination. No visual blocker remained after the final iteration.

## Remaining delivery conditions

1. Re-import or repair the date columns before making period-over-period or forecast claims.
2. Confirm the source currency and render it explicitly in KPI, chart, and narrative units.
3. Add regional profitability and high-discount-loss decomposition if the report is used for an
   executive review rather than as a platform acceptance sample.
