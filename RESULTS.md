# Results (run 20260814T033139Z)

This file records the final experimental results so the repository substantiates the numbers
reported in the thesis. Raw per-cell outputs are archived under `results/` (diagnostics,
judgments, calibration). The generator was GPT-4o at temperature 0.0; the judge was a
different model family (cross-family enforced in code).

## Completeness
- 120 decompositions (6 conditions x 20 frozen requirements), no missing cells, all schema-valid.
- 140 reconciled pairwise comparisons (7 comparison types x 20 requirements), both orders.
- Codebase-summaries index complete: 1088/1088 main-source files embedded.

## Layer 2 (file-existence grounding), mean hallucination rate
- Vanilla 0.703, Full RAG 0.496.
- SQ2 (vanilla vs full RAG): Wilcoxon p = 0.039, rank-biserial 0.57. Significant reduction.
- The reduction was a shift from hallucinated to AMBIGUOUS (0.230 -> 0.446); real rate ~unchanged
  (0.067 -> 0.058).
- SQ1 leave-one-out vs full RAG: no comparison significant after Holm-Bonferroni.

## Layer 3 (pairwise judge, DESCRIPTIVE only, gated by Layer 4)
- SQ2 full RAG vs vanilla: 7 vs 9 decided, sign test p = 0.80 (no quality advantage).
- SQ1: no leave-one-out significantly distinguished from full RAG.
- SQ3: full RAG 19/19 and vanilla 18/18 preferred over the human reference (p < 0.001), read as a
  format effect rather than substance.
- Positional inconsistency: 21/140 = 15%.

## Layer 4 (calibration gate)
- Overall Cohen's kappa = 0.56 (n = 19, 95% CI 0.19-0.94, raw agreement 0.84), below the 0.60 gate.
- FAIL: Layer 3 is reported descriptively; Layers 1-2 carry the primary conclusions.
- Single-annotator calibration; n small, so kappa is unstable. An LLM-filled rating sheet produced
  during the process was discarded as not independent human calibration. See
  docs/DECISION_LAYER4_calibration.md.

## Headline
Retrieval significantly improves grounding but not judged quality; no single context category shows
a significant contribution (a pre-registered null); and the judge could not be validated and
responds to format. These are case-study findings on a single project (Apache Pig).
