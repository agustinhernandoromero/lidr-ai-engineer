# Citation report: q01

- Query: Loan application platform with automatic credit scoring, KYC checks and electronic contract signing
- request_id: `c6c4648a`
- Model: claude-haiku-4-5-20251001 (anthropic), attempts: 1, prompt v1
- Retrieved chunks passed to the LLM: 5

## Retrieved context

| Chunk id | Component | Hours |
|---|---|---|
| `BUD-2024-002::ORIG-002` | Loan origination workflow | 180 |
| `BUD-2024-002::SCORE-001` | Credit scoring engine | 200 |
| `BUD-2024-002::SIGN-003` | E-signature integration | 80 |
| `BUD-2024-002::REPORT-004` | Regulatory reporting export | 60 |
| `BUD-2024-012::EDC-001` | Electronic data capture forms | 180 |

## Estimate lines and citation check

| Component | Hours | Status | Cited ids | Evidence |
|---|---|---|---|---|
| Loan origination workflow with KYC checks | 180 | grounded | `BUD-2024-002::ORIG-002` | Configurable application workflow with KYC checks, document upload, underwriting queue and automatic decisioning thresholds. Estimated hours: 180 |
| Automatic credit scoring engine | 200 | grounded | `BUD-2024-002::SCORE-001` | Rules-and-model based credit scoring service that ingests bureau data and bank statements, returning a risk band and recommended limit with full explainability logs. Estimated hours: 200 |
| Electronic contract signing integration | 80 | grounded | `BUD-2024-002::SIGN-003` | Integration with a qualified e-signature provider for legally binding loan contracts, including webhook handling and signed-document archival. Estimated hours: 80 |

Total of the grounded lines: 460 h

## Summary

- Grounded: 3
- Dangling citation: 0
- Evidence mismatch: 0
- Insufficient data: 0
- Check passed: True

## Planted dangling citation

`BUD-2023-099::PAY-001` added to the first grounded line, then the same check run again:
dangling lines ['Loan origination workflow with KYC checks'], check passed: False.

## Generated summary

This estimate covers the core components of a loan application platform: automatic credit scoring, KYC checks integrated into the origination workflow, and electronic contract signing. All three primary components are grounded in a directly comparable 2024 project. Regulatory reporting is not included as it was not requested.
