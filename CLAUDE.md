# Project context for Claude Code

This is the codebase for a finalized MSc thesis: "Context-Aware Requirements Decomposition with
Retrieval-Augmented LLMs" (Liverpool John Moores University). A RAG pipeline decomposes Apache Pig
business requirements into developer-ready user stories, and a four-layer framework evaluates the
outputs. The full proposal is the source of truth for every design decision. Guiding principle:
small objectives with genuine overdelivery, never large objectives left half-finished.

## The experiment in one paragraph
Twenty requirements are sampled from Apache Pig (SEOSS 33). Each runs under six conditions (vanilla,
full RAG, and four leave-one-out variants that each drop one context type), giving 120 generations.
Retrieval is hybrid (dense + lexical, fused with RRF, top 8), filtered per condition by context-type
metadata. Every generation is a fixed JSON decomposition, scored by four layers: structural metrics,
file-existence verification, pairwise LLM-judge ranking, and a researcher-calibrated kappa check.

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
Run `pytest` before and after changes. All of the above is covered by tests in `tests/`.

## What is scaffolded and needs wiring (this is the vibe-coding work)
- `src/retrieval/index.py`, `src/retrieval/hybrid.py` ChromaDB build and dense+lexical+RRF wiring.
- `src/pipeline/generate.py` retrieve -> build_prompt -> llm -> parse_decomposition.
- `src/eval/judge.py` render `prompts/judge_pairwise.txt`, call the judge, parse per-criterion winners.
- `src/eval/calibration.py` is ready; it just needs the researcher-vs-judge choice lists fed in.

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
1. DONE: `seoss_loader` + `sampling` are wired to the confirmed schema and tested. Next, run
   sample_requirements against the real db to freeze the twenty requirements and archive them.
2. Build the four context indexes (`index.py`) and complete hybrid retrieval (`hybrid.py`).
3. Complete `generate.py` and run the six conditions on the sanity-check requirements first.
4. Wire the judge (`judge.py`); Layers 1, 2, and the stats are ready to consume outputs.
5. Add the experiment runner that logs every layer to W&B / DVC.
