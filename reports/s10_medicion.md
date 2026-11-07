# Retrieval measurement (golden set of 5 queries, k=5, pool=50)

Annotation criterion: A budget is relevant if at least two of its components would serve as a credible effort reference for parts of the requested project (described in enough detail to estimate from). Annotated from the budget content alone, without looking at what the system retrieves.

## Summary

| Config | Search | Reranking | precision@5 | recall@5 | MRR | Retrieval latency (median) |
|---|---|---|---|---|---|---|
| A | vector | no | 0.24 | 1.00 | 0.90 | 49 ms |
| B | hybrid | no | 0.24 | 1.00 | 1.00 | 48 ms |
| C | vector | yes | 0.24 | 1.00 | 0.90 | 3873 ms |
| D | hybrid | yes | 0.24 | 1.00 | 0.90 | 3939 ms |

MRR (mean reciprocal rank): mean of 1 / position of the first relevant budget. It rewards order, which precision@k does not; 1.00 means the first relevant budget is always first.
Median latency of embedding the query: 288 ms (same for the four configurations, not included above).
Latency: median of 3 timed runs per query after one warm-up run.

## Conclusions

I would use configuration B (hybrid search, no reranking). The four configurations tie on precision@5 (0.24, which is also the best possible on this golden set because most queries have a single relevant budget) and on recall@5 (1.00). The only difference is order. B is the only one that puts the first relevant budget at position 1 in all five queries (MRR 1.00 against 0.90 for A, C and D): on q02 the lexical branch moves the two e-commerce budgets (005, 006) above the one-line MVP budget 017 that vector search ranks first. B costs the same as A (48 ms against 49 ms).

Reranking does not pay off here. C and D add about 3.9 s per query (roughly 80 times more) and do not improve any metric: on q05 the cross-encoder pushes the relevant warehouse budget (014) to position 2 behind 016, a banking migration, and on q02 it moves the second relevant budget (006) from position 3 to 4.

Caveats: the dataset has 17 budgets, so the pool of 50 candidates is the whole corpus; with 5 queries, a gain of one position in one query is all that separates B from A. On an earlier measurement over my own corpus of 15 budgets (docs/s10/medicion_own_corpus.md), hybrid was slightly worse than vector (precision 0.28 against 0.32, recall 0.90 against 1.00), so the evidence for hybrid is not stable, only the evidence against reranking is (it never helped on either corpus). If I had to keep one thing simple, vector search without reranking is the fallback. Reranking should be revisited with hundreds of budgets, where the pool of 50 is a real selection.

## precision@5 per query

| Query | Type | Relevant | Best possible | A | B | C | D |
|---|---|---|---|---|---|---|---|
| q01 | direct, frequent | 1 | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 |
| q02 | hard, neighbouring domains (e-commerce vs payments) | 2 | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 |
| q03 | exact term (FHIR) | 1 | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 |
| q04 | paraphrase, no shared words | 1 | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 |
| q05 | long and messy, like a meeting transcript | 1 | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 |

## Position of the first relevant budget per query (1 = best)

| Query | A | B | C | D |
|---|---|---|---|---|
| q01 | 1 | 1 | 1 | 1 |
| q02 | 2 | 1 | 1 | 1 |
| q03 | 1 | 1 | 1 | 1 |
| q04 | 1 | 1 | 1 | 1 |
| q05 | 1 | 1 | 2 | 2 |

## Top 5 budgets per query and configuration

**q01** relevant: BUD-2024-002
- A: BUD-2024-002 (relevant), BUD-2024-004, BUD-2024-012, BUD-2024-006, BUD-2024-003
- B: BUD-2024-002 (relevant), BUD-2024-012, BUD-2024-004, BUD-2024-003, BUD-2024-006
- C: BUD-2024-002 (relevant), BUD-2024-006, BUD-2024-014, BUD-2024-008, BUD-2024-015
- D: BUD-2024-002 (relevant), BUD-2024-006, BUD-2024-014, BUD-2024-008, BUD-2024-015

**q02** relevant: BUD-2024-005, BUD-2024-006
- A: BUD-2024-017, BUD-2024-005 (relevant), BUD-2024-006 (relevant), BUD-2024-003, BUD-2024-008
- B: BUD-2024-005 (relevant), BUD-2024-006 (relevant), BUD-2024-017, BUD-2024-003, BUD-2024-008
- C: BUD-2024-005 (relevant), BUD-2024-017, BUD-2024-003, BUD-2024-006 (relevant), BUD-2024-008
- D: BUD-2024-005 (relevant), BUD-2024-017, BUD-2024-003, BUD-2024-006 (relevant), BUD-2024-008

**q03** relevant: BUD-2024-009
- A: BUD-2024-009 (relevant), BUD-2024-012, BUD-2024-010, BUD-2024-001, BUD-2024-013
- B: BUD-2024-009 (relevant), BUD-2024-010, BUD-2024-001, BUD-2024-013, BUD-2024-012
- C: BUD-2024-009 (relevant), BUD-2024-010, BUD-2024-012, BUD-2024-016, BUD-2024-015
- D: BUD-2024-009 (relevant), BUD-2024-010, BUD-2024-012, BUD-2024-016, BUD-2024-015

**q04** relevant: BUD-2024-013
- A: BUD-2024-013 (relevant), BUD-2024-015, BUD-2024-010, BUD-2024-014, BUD-2024-005
- B: BUD-2024-013 (relevant), BUD-2024-016, BUD-2024-014, BUD-2024-006, BUD-2024-015
- C: BUD-2024-013 (relevant), BUD-2024-015, BUD-2024-007, BUD-2024-016, BUD-2024-014
- D: BUD-2024-013 (relevant), BUD-2024-015, BUD-2024-007, BUD-2024-016, BUD-2024-014

**q05** relevant: BUD-2024-014
- A: BUD-2024-014 (relevant), BUD-2024-011, BUD-2024-007, BUD-2024-008, BUD-2024-013
- B: BUD-2024-014 (relevant), BUD-2024-007, BUD-2024-011, BUD-2024-008, BUD-2024-006
- C: BUD-2024-016, BUD-2024-014 (relevant), BUD-2024-007, BUD-2024-004, BUD-2024-008
- D: BUD-2024-016, BUD-2024-014 (relevant), BUD-2024-007, BUD-2024-004, BUD-2024-008
