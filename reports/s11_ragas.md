# RAGAS: grounded estimator over the course golden set

- Date: 2026-11-15
- Generation: claude-haiku-4-5-20251001 (anthropic), prompt grounded_estimation/v1, hybrid retrieval without reranking, top 5 chunks
- ragas 0.4.3, Gemini judges through the OpenAI-compatible endpoint, embeddings gemini-embedding-001
- Judge per metric:
  - faithfulness: gemini-3.5-flash-lite
  - answer_relevancy: gemini-3.5-flash-lite
  - context_precision: gemini-3.5-flash
  - context_recall: gemini-3.5-flash-lite
- Metric calls that failed: 0
- Cells still pending: 0

| Query | Faithfulness | Answer relevancy | Context precision | Context recall |
|---|---|---|---|---|
| q01 | 0.80 | 0.72 | 1.00 | 0.80 |
| q02 | 0.06 | 0.65 | 0.87 | 0.80 |
| q03 | 0.50 | 0.76 | 1.00 | 0.75 |
| q04 | 0.92 | 0.73 | 1.00 | 1.00 |
| q05 | 0.56 | 0.68 | 1.00 | 0.40 |
| **Average** | **0.57** | **0.71** | **0.97** | **0.75** |

## Citations and totals per query

| Query | Total hours | Grounded lines | Dangling | Evidence mismatch | Insufficient | Check passed |
|---|---|---|---|---|---|---|
| q01 | 460 | 3 | 0 | 0 | 0 | True |
| q02 | 310 | 3 | 0 | 0 | 0 | True |
| q03 | 250 | 2 | 0 | 0 | 0 | True |
| q04 | 500 | 3 | 0 | 0 | 0 | True |
| q05 | 450 | 3 | 0 | 0 | 1 | True |
