# Project context for Claude Code

This is the codebase for a finalized MSc thesis: "Context-Aware Requirements Decomposition with
Retrieval-Augmented LLMs" (Liverpool John Moores University). A RAG pipeline decomposes Apache Pig
business requirements into developer-ready user stories, and a four-layer framework evaluates the
outputs. The full proposal is the source of truth for every design decision. Guiding principle:
small objectives with genuine overdelivery, never large objectives left half-finished.

## The experiment in one paragraph
Twenty requirements are sampled from Apache Pig (SEOSS 33). Each runs under six conditions (vanilla,
full RAG, and four leave-one-out variants that each drop one context type), giving 120 generations.
Retrieval is per-type (Option B): each context type retrieved independently, budget of 2 per type,
RRF fusing dense+lexical within a type. NOT global top-k. See docs/DECISION_retrieval_budget.md.
Do not revert to global top-k; it collapses three of four ablation arms. Every generation is a fixed JSON decomposition, scored by four layers: structural metrics, file-existence verification, pairwise LLM-judge ranking, and a researcher-calibrated kappa check.

## What is already implemented and tested (do not rewrite, match its style)
- `src/schema.py` the fixed decomposition JSON contract. Everything reads this shape.
- `src/conditions.py` the six conditions and four context types.
- `src/retrieval/fusion.py` Reciprocal Rank Fusion, k=50.
- `src/pipeline/prompt_assembly.py` the labelled-section prompt, requirement appended last.
- `src/eval/file_verifier.py` Layer 2, REAL / AMBIGUOUS / HALLUCINATED, with commit-window support.
- `src/eval/structural.py` Layer 1 diagnostic metrics.
- `src/eval/comparisons.py` Layer 3 pair generation: the seven comparison types, both orders.
- `src/analysis/stats.py` Wilcoxon signed-rank, rank-biserial effect size, Holm-Bonferroni, kappa.
- `src/data/seoss_loader.py` wired to the confirmed SEOSS schema (issues, commit trace links,
  files-per-commit, reference-artefact assembly, commit anchor for the Layer 2 window).
- `src/data/sampling.py` the twenty-requirement sampling with the Phase 1 relaxation chain.
- `src/data/commit_resolver.py` maps SEOSS commit hashes to the local clone. IMPORTANT: SEOSS built
  its change_set table from a different git conversion of Pig, so its hashes do NOT exist in the
  `apache/pig` clone even though every commit is present under a different hash. Do not try to "fix"
  this by re-cloning. Resolution is by message subject + author + date, and may return several local
  hashes; Layer 2 spans all of them via `FileVerifier.from_anchors`.
- `src/retrieval/index.py` ChromaDB build + dense_query with metadata filter and self-exclusion.
- `src/retrieval/hybrid.py` dense+lexical RRF, and retrieve_by_type (per-type Option B, budget 2).
- `src/pipeline/generate.py` run_condition wired (retrieve_by_type -> build_prompt -> llm -> parse).
- `src/eval/rendering.py` how a comparison side is shown to any rater. Shared by the judge and the
  Layer 4 sheet on purpose, so the researcher provably scores the same text the judge scored.
- `scripts/build_calibration_set.py` + `scripts/score_calibration.py` Layer 4: stratified blinded
  sample, hidden key, Cohen's kappa in sheet-position space, gate at 0.6 on the overall winner.
- `src/eval/judge.py` + `scripts/run_judge.py` Layer 3: renders judge_pairwise.txt, judges both
  presentation orders, reconciles per criterion and overall, writes judgments{,_raw}.jsonl. The
  judge is condition-blind (A/B only) and refuses to run from the generator's provider family.
Run `pytest` before and after changes. All of the above is covered by tests in `tests/`.

## What is scaffolded and needs wiring (this is the vibe-coding work)
- Full codebase-summaries pass: `python scripts/build_index.py --confirm-summaries` (all ~1088
  main-source files). Required before any real 120-run; the run is gated on
  assert_codebase_summaries_complete().
- Layer 4 rating: `data/runs/<run>/calibration/` holds a blinded sheet awaiting researcher ratings.
  Fill `calibration_ratings.csv`, then `python scripts/score_calibration.py --run-id <run>`.
- Experiment runner that logs every layer to W&B / DVC.

## Sampling criteria (decided from profiling the Pig dump, do not weaken)
- Candidate pool: type in (New Feature, Improvement), `resolution = 'Fixed'` (the loose
  resolved_date filter also admitted Duplicate / Won't Fix / Invalid), and a description length
  floor of 30 chars (drops the ~6% empty/near-empty descriptions that cannot be decomposed).
- The `is_merge` column is uniformly 0 in this dump, so no merge filter is applied; the real
  acceptance signal is "latest commit that touches code" (see anchor_commit_obj / _acceptance_commit).
- Deliberately OUT of the generation prompts: issue metadata like component, fix_version, and typed
  issue links. Adding them would inject project context outside the four-way ablation and contaminate
  the vanilla baseline. They are for sampling and analysis only. Do not feed them into prompts unless
  the ablation design is explicitly revised with the supervisor.

## Methodology discipline (from the proposal, do not regress)
- File verification is hard REAL / AMBIGUOUS / HALLUCINATED. Do not reintroduce a soft "plausible".
- Layers 1 and 2 are diagnostic (shape and grounding), Layers 3 and 4 are quality. Report them
  separately. More real file references does not mean a better decomposition.
- The judge is pairwise, both presentation orders reconciled, on a different model family from the
  generator. Do not switch it to independent Likert scoring (it saturates).
- Layer 3 counts as a primary quality signal only if Layer 4 kappa >= 0.6. Below that, report Layer 3
  descriptively.
- Generator temperature is fixed across all six conditions and recorded with results.
- SQ1 runs four paired tests per metric, so p-values get Holm-Bonferroni correction. Report
  rank-biserial effect sizes alongside, since n=20 has modest power and a clean null is still a result.

## Conventions
Python 3.11, type hints, Pydantic for structured data, `pathlib`, lazy imports for provider SDKs.
New pure/deterministic logic ships with tests against real fixtures, the way the file verifier builds
a throwaway git repo. Leave clear TODOs where a real value or schema is needed rather than inventing one.

## Writing style for any prose, comments, or docs
Natural and plain. No em dashes, no first-person pronouns in formal text, contractions are fine.
Explain the reasoning, not just the what.

## Build order (follows the twelve-week plan)
1. DONE: data layer (loader, sampling, commit resolver); 20 requirements frozen.
2. DONE: four context indexes + hybrid retrieval (Option B, per-type budget 2).
3. DONE: `generate.py` run_condition; verified end-to-end on the sanity requirements
   (retrieve -> generate -> parse -> Layer 2 correctly flags hallucinated files).
4. NEXT: full codebase-summaries pass (build_index --confirm-summaries), then it's valid to run
   all six conditions across the 20 frozen requirements (120 generations).
5. DONE: the judge (`scripts/run_judge.py --run-id <generation run>`), 140/140 on run
   20260814T033139Z. Layer 4 sheet is built and awaiting ratings. No win-rate or Bradley-Terry
   aggregation over judgments.jsonl exists yet.
6. Add the experiment runner that logs every layer to W&B / DVC.