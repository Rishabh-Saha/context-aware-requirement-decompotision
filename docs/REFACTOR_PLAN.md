# Refactor plan

Read-only survey of `src/`, `scripts/` and `tests/`. Nothing in the codebase was changed to produce
this. Baseline before any work starts: `pytest` is green, 131 passed in about 20 seconds.

Scope note. The experiment is finished and the reported numbers come from run `20260814T033139Z`.
That changes what a refactor is for. Nothing here should alter a number in RESULTS.md, so every
proposal below is judged on whether it can change behaviour on a re-run, not just on whether it
tidies the code.

## 1. Inventory

### src/ (6,497 total lines across the three trees; src is 2,046)

| File | Lines | What it does | Imported by |
| --- | --- | --- | --- |
| `src/__init__.py` | 0 | package marker | implicit |
| `src/schema.py` | 77 | the fixed decomposition JSON contract, Pydantic | generate, structural, run_experiment, 2 tests |
| `src/conditions.py` | 51 | six conditions, four context types, condition to context map | 18 files, the widest dependency in the repo |
| ~~`src/profiler.py`~~ | 42 | standalone fill-rate/cardinality dump of a SEOSS SQLite db | **moved to `scripts/profile_seoss.py`, item 1 done** |
| `src/utils/__init__.py` | 0 | package marker | implicit |
| ~~`src/utils/logging.py`~~ | 11 | logger factory with a fixed format | **deleted, item 1 done** |
| `src/utils/io.py` | 26 | write_json, write_jsonl, read_jsonl | 6 scripts |
| `src/llm/__init__.py` | 0 | package marker | implicit |
| `src/llm/base.py` | 38 | LLMClient ABC, LLMResponse, exponential-backoff retry | sources, 3 tests |
| `src/llm/openai_client.py` | 38 | OpenAI chat completion and batch embeddings | index, sources, hybrid, run_experiment, run_judge |
| `src/llm/anthropic_client.py` | 34 | Anthropic messages completion | run_experiment, run_judge |
| `src/analysis/stats.py` | 105 | Wilcoxon, rank-biserial, Holm-Bonferroni, Cohen's kappa | calibration, aggregate_results, test_stats |
| `src/data/seoss_loader.py` | 194 | every SQLite query against the SEOSS Pig dump | 10 files |
| `src/data/sampling.py` | 94 | twenty-requirement sample with the Phase 1 relaxation chain | freeze_requirements, test_seoss_loader |
| `src/data/commit_resolver.py` | 108 | SEOSS commit hash to local clone hash by subject/author/date | freeze_requirements, test_commit_resolver |
| `src/retrieval/chunking.py` | 19 | 500/50 splitter config, lazy LangChain import | index only |
| `src/retrieval/fusion.py` | 29 | Reciprocal Rank Fusion, k=50 | hybrid, test_fusion |
| `src/retrieval/text_clean.py` | 32 | strips Jira wiki markup, URLs, stack frames | sources, test_text_clean |
| `src/retrieval/sources.py` | 261 | builders for all four context types, including the cached LLM summary pass | index, build_index, 4 tests |
| `src/retrieval/index.py` | 151 | ChromaDB collection wrapper, upserts, dense query, coverage gate | build_index, sanity_retrieve, run_experiment, 2 tests |
| `src/retrieval/hybrid.py` | 146 | dense plus lexical RRF, self-exclusion, per-type retrieval | generate, 2 scripts, 2 tests |
| `src/pipeline/__init__.py` | 0 | package marker | implicit |
| `src/pipeline/prompt_assembly.py` | 45 | labelled-section prompt, requirement appended last | generate only |
| `src/pipeline/generate.py` | 82 | one (requirement, condition) cell: retrieve, prompt, generate, parse | run_experiment, 2 tests |
| `src/eval/__init__.py` | 0 | package marker | implicit |
| ~~`src/eval/base.py`~~ | 13 | `EvalRecord` dataclass for uniform layer logging | **deleted, item 1 done** |
| `src/eval/calibration.py` | 18 | kappa plus the 0.6 gate decision | score_calibration |
| `src/eval/structural.py` | 54 | Layer 1 structural metrics | run_experiment, test_structural |
| `src/eval/comparisons.py` | 63 | the seven comparison types, both orders, reconciliation | rendering, run_judge, 3 tests |
| `src/eval/rendering.py` | 112 | how a comparison side is shown to any rater, shared judge/researcher | run_judge, build_calibration_set |
| `src/eval/file_verifier.py` | 180 | Layer 2 REAL/AMBIGUOUS/HALLUCINATED against a commit window | run_experiment, 2 tests |
| `src/eval/judge.py` | 99 | judge prompt render, strict verdict parse, one pairwise call | run_judge, build_calibration_set, score_calibration, test |

Orphans, all three resolved by item 1. Nothing imported any of them. `profiler.py` was a genuine
research tool used to decide the sampling filters, so it was an orphan by location rather than by
value and moved to `scripts/profile_seoss.py`. `logging.py` and `base.py` were dead and were deleted:
every script prints directly and no layer ever built an `EvalRecord`.

### scripts/ (2,244 lines)

| File | Lines | What it does | Imported by |
| --- | --- | --- | --- |
| `scripts/profile_seoss.py` | 52 | fill rate, cardinality and value distribution per SEOSS column (moved from `src/` by item 1) | nothing, run by hand |
| `scripts/freeze_requirements.py` | 106 | freezes the twenty-requirement sample, write-once with `--check`/`--force` | nothing |
| `scripts/build_index.py` | 199 | populates the shared Chroma collection, gates the paid summary pass | test_build_index |
| `scripts/sanity_retrieve.py` | 116 | prints per-type retrieval and a self-exclusion leak check for one issue | nothing |
| `scripts/run_experiment.py` | 355 | the 20 x 6 generation grid plus Layers 1 and 2, resumable | test_run_experiment |
| `scripts/run_judge.py` | 360 | Layer 3 pass over an archived run, both orders, reconciled, resumable | test_run_judge |
| `scripts/build_calibration_set.py` | 327 | Layer 4 step one: stratified blinded sheet plus a separated key | test_calibration_set |
| `scripts/score_calibration.py` | 265 | Layer 4 step two: kappa in sheet-position space, applies the gate | test_score_calibration |
| `scripts/aggregate_results.py` | 256 | regenerates every Chapter 4 table from `results/` | nothing |

Three scripts have no test at all: `freeze_requirements.py`, `sanity_retrieve.py`,
`aggregate_results.py`. The first two are one-shot and already ran; `aggregate_results.py` is the
one that regenerates published numbers, so it is the notable gap.

### tests/ (2,207 lines, 131 tests)

| File | Lines | What it covers |
| --- | --- | --- |
| `tests/__init__.py` | 0 | package marker |
| `tests/test_build_index.py` | 82 | sanity summary scope, and that the `_meta` header is dropped |
| `tests/test_calibration_set.py` | 262 | stratification, seed reproducibility, and that no label leaks to the sheet |
| `tests/test_codebase_summaries.py` | 88 | the confirm gate and cache-first behaviour, with a fake LLM client |
| `tests/test_commit_resolver.py` | 67 | subject, Jira-key fallback and duplicate-subject resolution on a temp repo |
| `tests/test_comparisons.py` | 25 | seven types, both orders, reconcile agreement and conflict |
| `tests/test_file_verifier.py` | 74 | the three verdicts, rates, commit window, path normalisation |
| `tests/test_fusion.py` | 20 | RRF agreement, single list, tie-break determinism |
| `tests/test_hybrid.py` | 145 | fused retrieval against real Chroma, with self-exclusion including sub-tasks |
| `tests/test_index.py` | 105 | Chroma upsert idempotence, metadata filters, the coverage gate |
| `tests/test_retrieve_by_type.py` | 195 | per-type budget, leave-one-out drops exactly one type, prompt blocks |
| `tests/test_run_experiment.py` | 392 | diagnostics row shape and the resume path with a counting stub |
| `tests/test_run_judge.py` | 380 | strict parse, positional translation, resume, and blindness of the prompt |
| `tests/test_score_calibration.py` | 244 | kappa against a hand-computed 2x2, flipped sheets, drop-not-impute rules |
| `tests/test_seoss_loader.py` | 102 | loader queries and sampling against a real-schema fixture db |
| `tests/test_sources.py` | 96 | the three cheap context-type builders |
| `tests/test_stats.py` | 28 | Wilcoxon, rank-biserial, Holm-Bonferroni |
| `tests/test_structural.py` | 37 | Layer 1 metrics including the empty-decomposition case |
| `tests/test_text_clean.py` | 49 | code blocks, noformat, URLs, stack frames |

No orphan tests. Note that four test files import script modules by path
(`sys.path.insert(0, "scripts")` then `import run_experiment`), which couples them to helpers
defined at script level. That constrains proposal 1 below.

## 2. Findings

### 2.1 Helpers called exactly once

Named single-use steps inside a `main()` are a deliberate readability device here and are not the
problem. The ones worth naming are the cross-module ones and the ones that are pure indirection.

| Location | Helper | Single call site |
| --- | --- | --- |
| `src/schema.py:76` | `output_json_schema` | `src/pipeline/generate.py:43` |
| `src/schema.py:60` | `story_ids` | `src/schema.py:65` (own module) |
| `src/pipeline/generate.py:40` | `system_prompt` | `src/pipeline/generate.py:81` |
| `src/eval/structural.py:27` | `_story_cites_specific_file` | `src/eval/structural.py:48` |
| `src/eval/calibration.py:12` | `calibrate` | `scripts/score_calibration.py:156` |
| `src/retrieval/chunking.py:12` | `make_splitter` | `src/retrieval/index.py:75` |
| `src/retrieval/sources.py:165` | `_cache_key` | `src/retrieval/sources.py:170` |
| `src/retrieval/sources.py:50` | `_fix_undeclared_entities` | `src/retrieval/sources.py:99` |
| `src/analysis/stats.py:91` | `_rankdata` | `src/analysis/stats.py:39` |
| `src/data/sampling.py:37`, `:43` | `_has_discussion`, `_acceptance_commit` | `src/data/sampling.py:64-65` |
| `scripts/build_calibration_set.py:76` | `row_key` | `scripts/build_calibration_set.py:88` |
| `scripts/run_judge.py:131` | `prompt_fingerprint` | `scripts/run_judge.py:236` |
| `scripts/aggregate_results.py:44,48,52,56` | four one-line loaders | `main` |
| `scripts/aggregate_results.py:203` | `table_4_5_layer4` | `main` |

Never called in production at all, only from tests or nowhere:

- `src/data/seoss_loader.py:62` `distinct_types()`, `:66` `distinct_statuses()`. Zero call sites
  anywhere, including tests, and no mention in CODEBASE_GUIDE.md. These are the two that go.
- `src/data/seoss_loader.py:59` `meta()`. Zero call sites, but **keep**: documented in
  CODEBASE_GUIDE.md:53 as the read path for the `meta` provenance table.
- `src/data/seoss_loader.py:138` `commit_for_issue()`. Called only from `tests/test_seoss_loader.py`,
  but **keep**: documented in CODEBASE_GUIDE.md:263 alongside `anchor_commit_obj()`, and it has a
  passing test.
- `src/eval/file_verifier.py:135` `from_commit_window()`. Called only from `tests/test_file_verifier.py`;
  production always goes through `from_anchors()`.
- `src/retrieval/hybrid.py:63` `hybrid_retrieve()`. Called from `retrieve_by_type` with a one-type
  tuple, and from tests. Its "global top-k" entry-point framing is now historical, but the function
  itself is load-bearing.

### 2.2 Classes that hold no state

There are effectively none, which is worth saying plainly rather than manufacturing a finding.
`ContextIndex`, `FileVerifier`, `LocalCommitIndex`, `SeossLoader` and `LLMClient` all hold either a
lazily built handle or a preloaded lookup that exists precisely to avoid repeating expensive work.
`FileCheck`, `VerificationReport`, `ComparisonType`, `OrderedComparison`, `JudgeVerdict`, `Chunk`,
`Issue`, `Commit`, `LocalCommit`, `SampledRequirement` and `WilcoxonResult` are value objects, which
is the right shape for them.

The one exception was `src/eval/base.py:9` `EvalRecord`, which held no state because nothing ever
constructed it. Deleted by item 1.

### 2.3 Wrappers that only forward arguments

| Location | Wrapper | Forwards to |
| --- | --- | --- |
| `src/schema.py:76` | `output_json_schema()` | `Decomposition.model_json_schema()` |
| `src/conditions.py:50` | `active_contexts(c)` | `CONDITION_CONTEXTS[c]` |
| `src/eval/judge.py:35` | `load_template(path)` | `Path(path).read_text(...)` |
| `src/eval/calibration.py:12` | `calibrate(a, b)` | `cohens_kappa(a, b)` plus two dict keys |
| `src/data/seoss_loader.py:138` | `commit_for_issue(id)` | `anchor_commit_obj(id).commit_hash` |
| `src/retrieval/index.py:23` and `src/retrieval/hybrid.py:50` | `_default_embed_fn` (two copies) | `embed_texts` |
| `src/eval/file_verifier.py:179` | `verify(cands)` | list comprehension over `check` |
| `scripts/aggregate_results.py:44,48,52` | three loaders | `read_jsonl` |
| `scripts/aggregate_results.py:56` | `load_calibration` | `json.loads(path.read_text())` |

Two of these earn their keep and should stay: `active_contexts` is the ablation's public vocabulary,
and `_default_embed_fn` exists to keep the OpenAI SDK import lazy. The rest are indirection.

### 2.4 Exception handling that cannot fire, and dead guards

- `scripts/run_experiment.py:177` `return True   # unreachable, kept so every path returns a bool`.
  Self-documented dead code; the line above always raises.
- `scripts/score_calibration.py:158` `if kappa is None or (isinstance(kappa, float) and math.isnan(kappa))`.
  The `kappa is None` half cannot fire: `cohens_kappa` at `src/analysis/stats.py:82` always sets a
  rounded float. The `isnan` half is real and is exercised by a test, so only the None check is dead.
- `scripts/score_calibration.py:169` `if isinstance(ci, (list, tuple))`. Reaching this line requires
  `n >= 2`, and `cohens_kappa` always sets `ci95` to a tuple when `n > 1`, so the guard is always true.
- `src/retrieval/hybrid.py:95` `dense["ids"][0] if dense["ids"] else []`. Both the real Chroma
  response and the short-circuit at `src/retrieval/index.py:107` always populate `ids`.
- `src/retrieval/sources.py:179` `except (json.JSONDecodeError, OSError)` guards a file that
  `:176` just confirmed exists. `JSONDecodeError` is genuinely reachable on a truncated cache write;
  `OSError` is a stretch but harmless. Leave it.

Two related items that are not dead code but belong in the same list:

- `src/llm/base.py:34` catches bare `Exception` in the retry loop. A missing `OPENAI_API_KEY` raises
  `KeyError` at `openai_client.py:19` and gets retried three times with 2s and 4s sleeps before
  surfacing as an unrelated `RuntimeError`. Non-transient failures should not be retried.
- `src/data/commit_resolver.py:57` runs git with `check=True` and no handler, while
  `src/eval/file_verifier.py:82` wraps the identical call to give a readable error. Inconsistent.

### 2.5 Config keys

Only four config paths are ever read. Everything else in `config/config.yaml` is inert.

| Key | Read at | Status |
| --- | --- | --- |
| `llm.generator.*` | `run_experiment.py:215` | read, stamped into the manifest |
| `llm.judge.*` | `run_judge.py:217` | read, stamped into the manifest |
| `eval.file_verifier.commit_window_before/after` | `run_experiment.py:217-218` | read |
| `eval.judge.criteria` | `run_judge.py:218` | read **and cross-checked** against `judge.py:19`, which is the pattern the others should follow |
| `project` | nowhere | never read |
| `embedding.provider`, `embedding.model` | nowhere | never read; the model is hardcoded at `openai_client.py:33` |
| `retrieval.chunk_size`, `chunk_overlap` | nowhere | never read; duplicated as constants at `chunking.py:7-8` |
| `retrieval.top_k` | nowhere | never read; duplicated at `hybrid.py:31` |
| `retrieval.rrf_k` | nowhere | never read; duplicated at `fusion.py:11` |
| `data.seoss_db`, `data.repo_path` | nowhere | never read; duplicated as `DEFAULT_DB`/`DEFAULT_REPO` in five scripts |
| `data.n_requirements` | nowhere | never read; duplicated as `TARGET_N` at `sampling.py:21` |
| `eval.calibration.n_pairs` | nowhere | never read; duplicated as `DEFAULT_N` at `build_calibration_set.py:52` |
| `eval.calibration.kappa_threshold` | nowhere | never read; duplicated as `KAPPA_THRESHOLD` at `calibration.py:9` |
| `analysis.alpha`, `analysis.correction` | nowhere | never read; alpha is defaulted at `stats.py:60` |
| `tracking.wandb_project`, `tracking.use_dvc` | nowhere | never read; the tracking work was never done |

Every key also takes exactly one value, since there is one config file and one completed run. The
sharper problem is the second column of that table: eleven methodology values exist twice, once in
YAML and once in Python, and the Python copy is the one that ran. Editing `retrieval.top_k` in the
config today would change nothing and warn about nothing. `eval.judge.criteria` is the one key that
refuses to drift, and it does so by raising at `run_judge.py:219-220`.

### 2.6 Duplicated logic

| # | What | Where | Cost |
| --- | --- | --- | --- |
| 1 | Load frozen requirements, drop the `_meta` header | `run_experiment.py:62`, `run_judge.py:65`, `build_index.py:59`, `sanity_retrieve.py:52`, inline at `build_calibration_set.py:270` | five copies, three slightly different predicates |
| 2 | `append_jsonl` | `run_experiment.py:145`, `run_judge.py:123` | byte-identical; `utils/io.py` has `write_jsonl` but no append |
| 3 | Provider switch to build a client | `run_experiment.py:78` `make_llm`, `run_judge.py:83` `make_judge` | same body, branches in opposite order |
| 4 | `OVERALL` and `RATING_COLUMNS` | `build_calibration_set.py:60-61`, `score_calibration.py:47-48` | **the writer and the reader of the same CSV each define its columns independently** |
| 5 | `_default_embed_fn` | `index.py:23`, `hybrid.py:50` | two copies |
| 6 | Strip a ```json fence, same expression | `generate.py:29`, `judge.py:58` | two copies |
| 7 | Order-preserving dedupe | `file_verifier.py:111-115`, `file_verifier.py:147-150`, `commit_resolver.py:79-84`, `commit_resolver.py:102-107` | **four** copies, two per file, spelled two different ways (dict+setdefault, set+append) |
| 8 | "latest commit that touches code" | `seoss_loader.py:144` `anchor_commit_obj`, `sampling.py:43` `_acceptance_commit` | two implementations of one sampling rule, returning different types |
| 9 | The archived cell filename `{issue_key}__{condition}.json` | built at `run_experiment.py:74`, parsed at `rendering.py:102` | **the writer and the reader of the run directory agree only by convention** |
| 10 | `SRC_SUBPATH = "src/org/apache/pig"` | `build_index.py:52`, `run_experiment.py:56`, hardcoded at `sources.py:211` and `sources.py:230` | four copies |
| 11 | `sys.path.insert(0, parents[1])` preamble | all eight scripts | `pyproject.toml` already sets `pythonpath` for pytest, so only the scripts need it |
| 12 | `DEFAULT_DB`, `DEFAULT_REPO`, `DEFAULT_FROZEN`, `DEFAULT_RUNS_DIR`, `JUDGE_SUBDIR`, `CALIBRATION_SUBDIR` | spread across six scripts | many copies |

Items 4 and 9 are the two that can actually corrupt a result rather than merely annoy a reader.

### 2.7 Comments that restate the line below

The comment discipline here is good: nearly every comment explains a reason, which is the house
style and should be preserved. Genuine restatements are rare.

- `src/data/commit_resolver.py:60` `# %x00 -> git writes NULs into the output`, next to `%x00` in the
  format string.
- `src/analysis/stats.py:101` `# 1-based average rank`, next to `avg = (i + j) / 2 + 1`.
- `src/conditions.py:32` `# Which context types each condition retrieves over. VANILLA retrieves nothing.`
  next to a dict whose first entry is `Condition.VANILLA: ()`.
- `src/eval/file_verifier.py:111` `# Anchor is included in ancestors[0]; dedupe while preserving order.`
  The first clause is useful, the second restates the loop.

### 2.8 Docstrings longer than the function body

Clear cases:

| Location | Function | Docstring vs body |
| --- | --- | --- |
| `src/pipeline/generate.py:40` | `system_prompt` | 2 lines vs 1 |
| `src/eval/judge.py:39` | `render_judge_prompt` | 6 vs 1 |
| `src/eval/judge.py:88` | `judge_pair` | 7 vs 3 |
| `src/eval/rendering.py:89` | `requirement_text` | 2 vs 1 |
| `src/eval/rendering.py:95` | `load_decomposition` | 5 vs 4 |
| `src/retrieval/hybrid.py:55` | `self_exclusion_ids` | 4 vs 1 |
| `scripts/run_judge.py:73` | `side_of` | 5 vs 1 |
| `scripts/run_judge.py:131` | `prompt_fingerprint` | 5 vs 1 |
| `scripts/run_experiment.py:101` | `source_file_references` | 3 vs 1 |

This is the finding to be most careful with. In a thesis codebase the rationale is part of the
deliverable, and every one of these docstrings explains a methodological decision that the line
itself cannot: why `str.format` is safe against braces, why both orders exist at all, why duplicate
file references are kept. See section 4.

### 2.9 Pre-flight: which schema fields are reached by string

Required check before any item touches `src/schema.py` or `src/pipeline/generate.py`.

**`generate.py:37` is clean.** `_field(requirement, name)` has exactly three call sites, all string
literals, all inside `build_condition_prompt`:

| Call site | `name` | Resolves to |
| --- | --- | --- |
| `generate.py:50` | `"issue_key"` | `SampledRequirement.issue_key` (`sampling.py:28`) |
| `generate.py:51` | `"title"` | `SampledRequirement.title` (`sampling.py:29`) |
| `generate.py:52` | `"description"` | `SampledRequirement.description` (`sampling.py:30`) |

All three name fields on the *input* requirement, never on the *output* decomposition, so no
`schema.py` field is reachable through `_field`. `generate.py:37` is also the only `getattr` in
`src/` or `scripts/`. Both branches of `_field` raise on an unknown name (`KeyError` for the frozen
JSON dict, `AttributeError` for the dataclass), so a rename in `sampling.py` fails loudly.

**`src/eval/rendering.py:34-43` is not clean, and this is the flag.** Eight `schema.py` fields are
read by string key off a plain dict, every one through `.get()` with a default:

| Field | Read at | Failure mode if renamed in `schema.py` |
| --- | --- | --- |
| `epic_summary` | `rendering.py:34` | renders as an empty line |
| `user_stories` | `rendering.py:35` | renders zero stories |
| `id`, `story` | `rendering.py:36` | renders `Story :` with an empty body |
| `acceptance_criteria` | `rendering.py:37` | criteria silently omitted |
| `complexity` | `rendering.py:39` | renders `Complexity:` with no value |
| `dependencies` | `rendering.py:40` | section silently omitted |
| `source_files` | `rendering.py:42` | section silently omitted |

None of these raise. A `schema.py` rename would degrade the rendered text rather than break the run,
and `rendering.py` is the module that produces the stimulus for both the Layer 3 judge and the Layer
4 sheet, so the degraded text would become what a rater scored with nothing on disk to say so.

The dict itself arrives from `rendering.py:105`, which reads `["decomposition"]` out of an archived
cell file, so these are `model_dump()` outputs of a `Decomposition` and the coupling is real rather
than incidental. Two consequences for the plan:

- Any item touching `src/schema.py` field names must update `rendering.py:34-43` in the same commit.
  No test would catch the omission: `test_run_judge.py` and `test_calibration_set.py` build their
  decomposition fixtures with the same string literals, so both would drift together.
- Worth considering on its own merits, outside this plan: have `render_decomposition` validate
  through `Decomposition.model_validate` and read attributes, so the contract is enforced at the one
  point where a rater-facing artefact is produced.

### 2.10 Functions over 40 lines or nested more than 3 deep

| Location | Function | Lines | Max nesting |
| --- | --- | --- | --- |
| `scripts/run_experiment.py:192` | `main` | 160 | 5 |
| `scripts/run_judge.py:205` | `main` | 152 | 4 |
| `scripts/build_calibration_set.py:242` | `main` | 82 | 3 |
| `scripts/score_calibration.py:187` | `main` | 75 | 3 |
| `scripts/sanity_retrieve.py:57` | `main` | 57 | 4 |
| `scripts/build_index.py:146` | `main` | 50 | 3 |
| `scripts/freeze_requirements.py:59` | `main` | 44 | 3 |
| `src/retrieval/sources.py:217` | `codebase_summary_chunks` | 45 | 3 |
| `src/retrieval/hybrid.py:103` | `retrieve_by_type` | 44 | 2 |
| `src/data/sampling.py:52` | `sample_requirements` | 43 | 4 |
| `scripts/build_calibration_set.py:176` | `write_sheet_markdown` | 41 | 2 |
| `src/data/commit_resolver.py:73` | `resolve` | 36 | 4 |
| `tests/test_run_experiment.py:225` | `experiment` fixture | 57 | 3 |
| `tests/test_run_judge.py:96` | `workspace` fixture | 47 | 3 |

`run_experiment.main` is the outlier by a wide margin: 160 lines, argument parsing through gate
checks through manifest writing through a doubly nested loop with a `try` inside it.

### 2.11 Leftover debug output

Not on the requested list, but it belongs in the same sweep.

- `src/retrieval/sources.py:85, 112, 139, 260`: `print(chunks[:5])` dumps five full `Chunk` objects,
  including entire file bodies for coding conventions, into the build log four times.
- `src/data/seoss_loader.py:109`: prints the SQL and params on every `issues()` call, including from
  inside the test suite.
- Unused imports: `scripts/run_judge.py:44,46` imports `REFERENCE`, `load_decomposition`,
  `render_decomposition`, `render_reference` and `scrub_artefact`, none of which appear in its body
  (it goes through `resolve_side`). `scripts/profile_seoss.py:16` imports `textwrap` unused.

  **Correction, found while executing item 2: four of those five are unused, not all five.**
  `scrub_artefact` is reached as `run_judge.scrub_artefact` from `tests/test_run_judge.py:230,240`,
  so removing it broke two tests. Static import analysis cannot see cross-module attribute access.
  `scrub_artefact` is now kept as an explicit re-export with `F401` and a comment saying why.

  **Second correction, found while executing item 4.** The list published here after item 2 was
  itself incomplete, because it was grepped for literal module names and
  `tests/test_calibration_set.py:19` does `import build_calibration_set as bcs`. The list below is
  AST-derived and alias-aware, and is the authoritative one.

  | Script | Name reached by attribute | From |
  | --- | --- | --- |
  | `build_calibration_set` | `CRITERIA`, `DESIGN_WEIGHTS`, `main`, `stratum_targets` | `test_calibration_set.py` |
  | `build_index` | `frozen_requirements`, `sanity_summary_scope` | `test_build_index.py` |
  | `run_experiment` | `build_verifier`, `cell_paths`, `diagnostics_row`, `existing_diagnostic_keys`, `frozen_requirements`, `main`, `source_file_references` | `test_run_experiment.py` |
  | `run_judge` | `CRITERIA`, `main`, `scrub_artefact`, `side_of` | `test_run_judge.py` |
  | `score_calibration` | `CRITERIA`, `KAPPA_THRESHOLD`, `main` | `test_score_calibration.py` |

  **Third correction, the sweep widened before item 10.** The alias-aware list above was still
  short, and the count of 19 was itself a miscount of 20. `monkeypatch.setattr(run_judge,
  "make_judge", stub)` passes the attribute name as a string constant, so it is not an
  `ast.Attribute` node and no dotted-access walk will ever see it. Five names are reached only that
  way, and they are the most consequential five in the file, because each one is an **imported name
  being replaced inside the script's own namespace**.

  Authoritative list, 24 names. Star imports: none. `getattr`/`hasattr` by string: none.
  `importlib`, `globals()`, `eval`, `exec`: none.

  | Script | Reached by dotted access | Reached by string-name patching |
  | --- | --- | --- |
  | `build_calibration_set` | `DESIGN_WEIGHTS`, `main`, `stratum_targets` | none |
  | `build_index` | `frozen_requirements`, `sanity_summary_scope` | none |
  | `run_experiment` | `build_verifier`, `cell_paths`, `diagnostics_row`, `existing_diagnostic_keys`, `frozen_requirements`, `main`, `source_file_references` | `ContextIndex`, `SeossLoader`, `build_condition_prompt`, `make_llm` |
  | `run_judge` | `CRITERIA`, `main`, `scrub_artefact`, `side_of` | `make_judge` |
  | `score_calibration` | `CRITERIA`, `KAPPA_THRESHOLD`, `main` | none |

  Any sweep run in future must cover four vectors, not one: dotted access, `setattr`/`monkeypatch.
  setattr` with a string name, star imports, and dynamic lookup. Three successive sweeps
  under-counted this, so treat any number produced here as a floor until a proposed move is actually
  attempted and the suite run.

  **That re-export is a temporary measure, not a pattern to copy.** No further re-exports are to be
  added outside item 8 step 1, where they exist only to keep the suite green between the move and the
  test update, and are deleted in step 2.

  This generalises past item 2. **Any proposal that removes or moves a script-level name must be
  checked against that attribute-access list first**, not just against imports. It is the concrete
  form of the risk noted for item 8, and it is why item 8 is rated medium.

## 3. Where the complexity is

Four files carry it, and they are all in `scripts/`:

1. **`scripts/run_experiment.py`** (355 lines). A 160-line `main` at depth 5 that owns resume logic,
   the coverage gate, manifest provenance, per-cell archiving and per-cell failure isolation. It is
   the only place three separate correctness properties meet: never re-pay for a generation, never
   let one bad cell kill the other 119, and never let an incomplete index masquerade as a full run.
2. **`scripts/run_judge.py`** (360 lines). A 152-line `main` at depth 4 with the same resume and
   failure-isolation shape as above, plus the positional translation and the different-family guard.
   Structurally it is `run_experiment` again with different nouns, which is why finding 2.6 has so
   many entries between these two files.
3. **`scripts/build_calibration_set.py`** (327 lines) and **`scripts/score_calibration.py`** (265).
   Best read as one unit, since they are the writer and reader of the same blinded CSV. Complexity
   here is genuinely conceptual, not accidental: stratified sampling, an independent coin flip, a
   separated key, and a translation between two rating vocabularies. The accidental part is that the
   two halves of that contract are stated twice (finding 2.6, item 4).

Those four files are 1,307 lines, 58 percent of `scripts/` and 20 percent of the codebase.

In `src/`, complexity is comparatively well distributed. The three densest files are
`file_verifier.py` (180), `seoss_loader.py` (194) and `sources.py` (261), and all three are dense
because the domain is: git tree resolution, a real SQL schema, and four different source formats.
None of them needs restructuring.

## 4. Ranked proposals

Ordered by value per unit of risk. "Lines" is net removal, ignoring any new shared module.

| # | Change | Files | Lines | Risk |
| --- | --- | --- | --- | --- |
| 1 | ~~Delete `src/utils/logging.py` and `src/eval/base.py`; move `src/profiler.py` to `scripts/profile_seoss.py`~~ **DONE** | 3 | 24 | **low** |
| 2 | ~~Remove the **four** unused imports in `run_judge.py` (not five, see 2.11) and one in `profile_seoss.py`~~ **DONE** | 2 | 5 | **low** |
| 3 | ~~Remove the four `print(chunks[:5])` calls and the SQL print in the loader~~ **DONE** | 2 | 5 | **low** |
| 4 | ~~Single-source `RATING_COLUMNS`/`OVERALL` into `src/eval/calibration.py`, plus the test edit~~ **DONE** | 4 | 6 | **medium** |
| 5 | ~~Single-source the cell filename: one `cell_stem(issue_key, condition)` used by both the writer and `rendering.load_decomposition`~~ **DONE**, verified against all 120 archived cells | 2 | 4 | **low** |
| 6 | Delete `distinct_types()` and `distinct_statuses()` only (see 2.1: `meta()` and `commit_for_issue()` stay, both documented in CODEBASE_GUIDE.md) | 1 | ~10 | **low** |
| 7 | Collapse `aggregate_results`'s four one-line loaders and `table_4_5_layer4` into `main` | 1 | ~16 | **low** |
| 8 | Move `append_jsonl`, `frozen_requirements` and the client factory into `src/utils/` and `src/llm/`; delete the five/two/two copies | 7 | ~70 | **medium** |
| 9 | ~~One order-preserving `dedupe()` in `src/utils/`~~ **DONE**, **four** copy sites not three | 3 | 14 | **low** |
| 10 | ~~Share script defaults from one `src/paths.py`~~ **DONE**, 14 constants, 8 scripts plus 3 sites in `src/` | 11 | 30 | **low** |
| 11 | Delete the dead guards: `run_experiment.py:177`, the `kappa is None` half at `score_calibration.py:158`, the `isinstance` at `:169`, the `dense["ids"]` falsy branch at `hybrid.py:95` | 3 | ~6 | **low** |
| 12 | Split `run_experiment.main` into `parse_args`, `prepare_run` and `run_cell`, flattening depth 5 to 3 | 1 | ~0 net | **medium** |
| 13 | Same split for `run_judge.main` | 1 | ~0 net | **medium** |
| 14 | Reconcile `config/config.yaml` with the code: either read the eleven duplicated keys, or delete them and leave a comment pointing at the module that owns each value | 6+ | ~15 yaml | **medium** |
| 15 | Inline the pure-indirection wrappers: `output_json_schema`, `system_prompt`, `load_template`, `calibrate` | 5 | ~15 | **medium** |
| 16 | Narrow the retry in `src/llm/base.py:34` to transient errors so a missing API key fails immediately | 1 | ~+5 | **medium** |
| 17 | Fold `sampling._acceptance_commit` into `loader.anchor_commit_obj` | 2 | ~8 | **high** |
| 18 | Trim the docstrings named in 2.8 | 5 | ~25 | **high** |

Notes on the ones where the risk rating is doing real work.

**Item 4 is blocked, and was mis-rated low.** Attempted and reverted. Moving `RATING_COLUMNS` and
`OVERALL` into `src/eval/calibration.py` works on the `score_calibration.py` side, which keeps
`CRITERIA` for its own loops. It fails on the `build_calibration_set.py` side: that script's *only*
use of `CRITERIA` is to build `RATING_COLUMNS`, so the move makes the import dead, but
`tests/test_calibration_set.py` reaches `bcs.CRITERIA` at lines 50, 173 and 260. Removing it raises
`AttributeError` in 12 tests.

Worth noting what those test lines actually do: `:173` asserts
`manifest["rating_columns"] == [*bcs.CRITERIA, "overall"]` and `:260` asserts the CSV header the same
way. The test therefore holds a *third* independent construction of the column list, rebuilt from
`CRITERIA` and a literal `"overall"`, rather than asserting against `RATING_COLUMNS`. So the drift
risk this item exists to remove is currently spread across three places, not two.

**Resolved by option 1 below.** Before editing, the assertion was confirmed load-bearing by mutation:
setting `RATING_COLUMNS = ("wrong_column", OVERALL)` failed three tests in `test_calibration_set.py`
with explicit column diffs. After the change, both directions were re-checked by mutation and both
are still caught, though by different tests than before:

| Mutation | Caught by |
| --- | --- |
| wrong `RATING_COLUMNS` at the shared definition | `test_score_calibration.py`, 4 tests (the reader stops parsing real criterion columns) |
| writer stops using `RATING_COLUMNS` for the CSV header | `test_calibration_set.py`, 1 test |

Coverage did not fall, it moved to the reader side, which is the better place for it: the writer is
now checked for *using* the shared definition, and the definition itself is checked by the reader
that has to parse real data with it.

Three ways forward, in preference order:

1. Move the constants to `src/eval/calibration.py` and update `test_calibration_set.py` to import
   `RATING_COLUMNS` from there, replacing `[*bcs.CRITERIA, "overall"]` with it. This removes all
   three copies and makes the test assert against the shared definition, which is stronger than what
   it asserts today. Costs a three-line test edit.
2. Same move, but keep `CRITERIA` in `build_calibration_set.py` as an `F401` re-export. Cheapest, and
   explicitly ruled out: re-exports are reserved for item 8 step 1.
3. Leave item 4 undone and accept the duplication.

Needs a decision before this item can proceed.

**Item 8's split into 8a and 8b was wrong, corrected by the widened sweep.** The earlier claim that
`append_jsonl` and the client factory are reached by no test, and so could move without any test
edit, holds only for `append_jsonl`. `run_experiment.make_llm` and `run_judge.make_judge` are both
replaced by `monkeypatch.setattr` with a string name, which no dotted-access sweep reports. Moving
either into `src/llm/` makes the script bind the name via `from ... import`, and the patch target
disappears, so `test_run_experiment.py:259` and `test_run_judge.py:146` would fail with
`AttributeError`. The corrected split:

- **8a**, genuinely no test edits: `append_jsonl` only. Two identical copies, reached by nothing.
- **8b**, needs test edits: `frozen_requirements` (5 copies; `test_run_experiment.py`,
  `test_build_index.py`) and the client factory (2 copies; `test_run_experiment.py`,
  `test_run_judge.py`). For the factory the fix is not a re-export but patching the new location,
  or having the script keep a thin `make_llm` that delegates, which is what the tests are really
  asserting against anyway.

The same hazard applies to `run_experiment.ContextIndex`, `SeossLoader` and `build_condition_prompt`:
all three are imported names patched in place, so any item that changes how `run_experiment.py`
imports them breaks the resume test. Item 12's split of `main` must leave those three bindings at
module level.

**Item 8, medium not low.** Four test files import script modules by path and reference script-level
helpers directly (`test_build_index.py` calls `run script's frozen_requirements`). Moving those
helpers out requires editing tests in the same commit, which means the test suite stops being an
independent check of the move. Do it in two steps: move the implementation into `src/`, leave a
one-line re-export in the script, confirm green, then delete the re-export and update the tests.

**Items 12 and 13, medium.** `run_experiment.py` is covered by a resume test with a counting stub,
which is exactly the property most likely to break, so the safety net is real. But the file also
owns failure isolation, and a mis-scoped `try` during the split would turn a recoverable cell
failure into a lost run. Behaviour-preserving extraction only, no reordering.

**Item 14, medium.** Deleting the unread keys is a two-line diff, but those keys are also the only
place several methodology values are written down in one human-readable file, which has audit value
for a thesis. Making the code read them instead is the better direction but is a behaviour change on
a completed run. See the question in section 6.

**Item 15, and anything else touching `schema.py` or `generate.py`.** Run the section 2.9 check
first. Inlining `output_json_schema` and `system_prompt` is safe as written, since neither renames a
field, but the moment a field name moves, `rendering.py:34-43` must move with it in the same commit
and no test will say otherwise.

**Item 16, medium.** This changes how a re-run fails, not what it produces. Worth doing, but it is a
behaviour change on a pipeline whose outputs are already published, so it should be a named commit.

**Item 17, high.** `sampling._acceptance_commit` feeds `resolution_commit` in the frozen requirements
file, which is a locked Phase 1 deliverable, while `anchor_commit_obj` feeds the Layer 2 window. The
two agree today because they implement the same rule, but unifying them touches the sampling path.
If this is done at all, the safe version is to add a test asserting the two produce the same hash for
all twenty frozen requirements, and leave both implementations in place.

**Item 18, high.** Not high risk to behaviour, high risk to the deliverable. See below.

## 5. Leave alone

These look like redundancy and are not.

- **`src/eval/rendering.py` as a shared module.** Both the judge and the Layer 4 sheet importing the
  same renderers is the mechanism that makes "the researcher saw what the judge saw" a property of
  the code. Do not let a refactor give either caller its own copy.
- **`hybrid_retrieve` called with a one-type tuple by `retrieve_by_type`.** It looks like a wrapper
  around a wrapper. It is the reason per-type retrieval is not a second code path with its own
  self-exclusion bug, and `docs/DECISION_retrieval_budget.md` explains why global top-k must not
  come back.
- **The strict parse in `src/eval/judge.py:50`.** Every raise there is deliberate; a defaulted
  verdict would be indistinguishable from a real one downstream.
- **Hard REAL/AMBIGUOUS/HALLUCINATED in `file_verifier.py`.** No soft category, per CLAUDE.md.
- **Judging both presentation orders and reconciling to null on disagreement.** The inconsistency
  rate is itself a reported number.
- **The confirm gates**: `sources.py:236` (`confirm=True` for the paid summary pass), the `--force`
  guards at `freeze_requirements.py:91` and `build_calibration_set.py:261`, and
  `index.assert_codebase_summaries_complete`. Each one guards something irreversible or expensive.
- **The explicit `CONDITION_CONTEXTS` table at `conditions.py:33`.** It could be generated from
  `LEAVE_ONE_OUT`, but the ablation design being readable in one glance is worth six lines.
- **The rationale-carrying docstrings in 2.8.** They are longer than their bodies because the body
  is trivial and the reason is not. `judge_pair`'s docstring is where the different-family
  requirement is written down; `source_file_references`'s is where the decision to count duplicate
  references is recorded. Trimming these makes the code shorter and the thesis worse. If item 18 is
  done at all, restrict it to `requirement_text` and `system_prompt`, where the docstring genuinely
  restates the body.
- **`results/` and `data/frozen/requirements.json`.** Published artefacts of a completed run.

## 6. Questions

1. **What is this refactor for?** A tidied artefact submitted alongside the thesis, or post-submission
   maintenance? If the code is assessed as the deliverable for run `20260814T033139Z`, that argues
   for items 1 to 11 only and against 12 to 18.
2. **Should `config/config.yaml` become authoritative, or documentary?** Right now eleven values live
   in both YAML and Python and the Python copy is what ran. Making the code read the config is
   correct but is a behaviour change; deleting the unread keys is safe but loses a readable record of
   the methodology in one place. There is a third option: keep the keys and add startup assertions
   that they match the module constants, the way `run_judge.py:219` already does for `criteria`.
3. **May tests be edited in the same commits?** Item 8 cannot be done without it, and that
   temporarily weakens the suite as an independent check of the move.
4. ~~**`src/profiler.py`: move or delete?**~~ Answered by executing item 1: moved to
   `scripts/profile_seoss.py` and given a usage header matching its new siblings.
5. **Were the `print(chunks[:5])` calls in `sources.py` deliberate build-log output, or leftovers?**
   They print whole file bodies, which reads like debugging, but the index build is a one-shot
   operation where a visible sample may have been the point.
6. **Should scripts keep the `sys.path.insert` preamble?** Switching to `python -m scripts.run_experiment`
   removes eight copies of it, but invalidates the usage lines in every script docstring and in
   README/CODEBASE_GUIDE.
7. **Is `aggregate_results.py` worth a test?** It is the only untested script that regenerates
   published numbers, and it is untested precisely because it consumes fixed artefacts. A small
   fixture-based test would make items 7 and 10 safe to do without re-running anything.
