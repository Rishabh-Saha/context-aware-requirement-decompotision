# Refactor record

What was surveyed, what was changed, what was deliberately not changed, and what a future pass needs
to know before it starts. This began as a read-only proposal and is kept as a record of the work that
followed, so the reasoning behind each decision survives the commits.

Scope. The experiment is finished and every reported number comes from run `20260814T033139Z`.
Nothing here was allowed to alter a number in RESULTS.md, so each change was judged on whether it
could change behaviour on a re-run, not on whether it tidied the code.

## Verification standard

Every executed item was held to three checks, run before committing:

1. `pytest`, which must stay at 131 passed.
2. `scripts/aggregate_results.py --run-id 20260814T033139Z`, diffed against a golden capture of its
   output taken before any change.
3. `sha256sum -c` over the nine committed `results/` artefacts and `data/frozen/requirements.json`.

All twelve commits passed all three. Several items carried an additional check specific to what they
touched, noted per item below. Where a change could not be proved safe by the standard three, the
extra check is the one that actually did the work.

## Executed

| Item | Change | Commit | Extra verification |
| --- | --- | --- | --- |
| 1 | Deleted `src/utils/logging.py` and `src/eval/base.py`; moved `src/profiler.py` to `scripts/profile_seoss.py`, folding in its unused `textwrap` import | `94b30f3` | moved script re-run from its new location |
| 2 | Dropped four unused imports from `run_judge.py` | `21c11ca` | see corrections: the survey said five |
| 3 | Removed four `print(chunks[:5])` object dumps and the loader's SQL print | `15cdfca` | confirmed no test reads stdout |
| 4 | Single-sourced `OVERALL` / `RATING_COLUMNS` into `src/eval/calibration.py`, plus the test edit | `e57b453` | mutation-checked before and after, see below |
| 5 | Single-sourced the archived cell filename as `rendering.cell_stem` | `e0c5e76` | all 120 archived cells resolve, load and validate, both directions, prompt files included |
| 10 | Consolidated 14 default locations into `src/paths.py` | `19ce394` | every constant proved byte-identical to its former value |
| 9 | One order-preserving `dedupe()` in `src/utils/sequences.py` | `bfcc40f` | differential run on real data: 40 anchors, 20 requirements, 791 SEOSS commits, order included |
| 11 | Deleted four unreachable guards | `b27a47f` | each replaced by an assertion first, no probe fired |
| 6 | Deleted `distinct_types()` and `distinct_statuses()` | `cf8c362` | `meta()` and `commit_for_issue()` confirmed still working |
| 7 | Inlined five pass-through loaders in `aggregate_results.py` | `c9705b5` | written `aggregates.json` byte-identical, key order included |
| 8a | Moved `append_jsonl` into `src/utils/io.py` | `5fe3fbf` | append semantics checked directly |
| 8b | `load_frozen_requirements` into `src/data/frozen.py`, `make_client` into `src/llm/factory.py` | `56639e8` | predicate equivalence on the real frozen file, delegate mutation-checked both ways |

### Item 8b carries a behaviour change

The five frozen-file loaders used two different predicates. Four filtered on
`isinstance(r, dict) and r.get("issue_key")`, one on `"_meta" not in r`. They agree on the real file,
verified element-for-element, and diverge on a malformed one: the loose form keeps a record with no
issue_key, keeps a bare string (because `in` on a str is a substring test, not a type error), and
raises `TypeError` on an int. The strict form is now used everywhere. This is the only intentional
behaviour change in the twelve commits, and it affects malformed input only.

Three copies of the loose predicate remain in `freeze_requirements.py` at lines 78, 79 and 97. That
script writes the frozen file rather than reading it, and two of those operate on an in-memory list,
so folding them needs a `strip_meta` helper rather than the loader. Left as follow-up work.

### What the mutation checks established

Item 4's assertion was confirmed load-bearing before being changed: a wrong `RATING_COLUMNS` failed
three tests with explicit column diffs. After the change both directions were re-checked, because
moving an assertion onto a shared definition can hollow it out. It did not. A wrong definition now
fails four tests in `test_score_calibration.py`, and a writer that stops using it fails one in
`test_calibration_set.py`. Coverage moved to the reader rather than dropping.

Item 8b's delegate check produced a result that contradicted the prediction it was written against,
and the correction is the useful part. Breaking `make_client` leaves all 36 tests passing, as
expected. Breaking the *body* of `make_llm` / `make_judge` also leaves them passing, because
`monkeypatch.setattr` replaces the function object and the body is unreachable by construction. The
seam is the **delegate name existing**, not its body running. Removing the name fails 10 tests with
9 errors on `AttributeError: module has no attribute 'make_judge'`.

Consequence for later work: any change that inlines those two delegates breaks both resume tests, and
no body-level test will warn about it first.

## Deferred

Items 12 to 18 were deferred by decision, not by difficulty. The survey reasoning for each is kept
here so a future pass does not have to re-derive it.

| Item | Change | Why deferred |
| --- | --- | --- |
| 12 | Split `run_experiment.main`, 160 lines at nesting depth 5, into `parse_args` / `prepare_run` / `run_cell` | Behaviour-preserving extraction only. The file owns resume and per-cell failure isolation, and a mis-scoped `try` would turn a recoverable cell failure into a lost run. Constrained by the sweep: `ContextIndex`, `SeossLoader` and `build_condition_prompt` must stay bound at module level |
| 13 | Same split for `run_judge.main`, 152 lines at depth 4 | Same shape, same constraint via `make_judge` |
| 14 | Reconcile `config/config.yaml` with the code | Eleven methodology values exist twice, once in YAML and once as a Python constant, and the Python copy is what ran. Editing `retrieval.top_k` today changes nothing and warns about nothing. Three options: make the code read them, delete the unread keys, or assert they match at startup the way `run_judge.py` already does for `criteria`. Needs a decision, not a refactor |
| 15 | Inline the pure-indirection wrappers `output_json_schema`, `system_prompt`, `load_template`, `calibrate` | Safe as specified, but read the schema-fields note below first |
| 16 | Narrow the retry in `src/llm/base.py` to transient errors | A missing `OPENAI_API_KEY` raises `KeyError` and is retried three times with 2s and 4s sleeps before surfacing as an unrelated `RuntimeError`. Changes how a re-run fails, not what it produces, so it deserves its own named commit |
| 17 | Fold `sampling._acceptance_commit` into `loader.anchor_commit_obj` | High risk. `_acceptance_commit` feeds `resolution_commit` in the locked Phase 1 frozen file. The safe version is a test asserting the two agree across all twenty frozen requirements, leaving both implementations in place |
| 18 | Trim the docstrings longer than their function bodies | Low risk to behaviour, high risk to the deliverable. Most are where a methodological decision is written down. Restrict to `requirement_text` and `system_prompt`, where the docstring genuinely restates the body |

## Standing notes for anyone picking this up

### 1. Four analysis vectors, not one

Three successive sweeps of this codebase under-counted, each time because the previous one covered
too few vectors. Any sweep for "what reaches this name" must cover all four:

| Vector | Example | Why grep and a simple AST walk miss it |
| --- | --- | --- |
| Dotted access | `run_experiment.cell_paths` | caught by an `ast.Attribute` walk, but only if module aliases are resolved first |
| Module aliasing | `import build_calibration_set as bcs` then `bcs.CRITERIA` | a grep for the module name finds nothing |
| String-name patching | `monkeypatch.setattr(run_judge, "make_judge", stub)` | the attribute is a string constant, so it is not an `ast.Attribute` node at all |
| Dynamic lookup | star imports, `getattr`, `globals()`, `importlib` | none present today, but must be re-checked rather than assumed |

Current count: **24 script-level names are load-bearing for the test suite without appearing in any
import statement.** Treat that as a floor. Verify a proposed move by attempting it and running the
suite, not by trusting a sweep.

| Script | Dotted access | String-name patching |
| --- | --- | --- |
| `build_calibration_set` | `DESIGN_WEIGHTS`, `main`, `stratum_targets` | none |
| `build_index` | `sanity_summary_scope` | none |
| `run_experiment` | `build_verifier`, `cell_paths`, `diagnostics_row`, `existing_diagnostic_keys`, `main`, `source_file_references` | `ContextIndex`, `SeossLoader`, `build_condition_prompt`, `make_llm` |
| `run_judge` | `CRITERIA`, `main`, `scrub_artefact`, `side_of` | `make_judge` |
| `score_calibration` | `CRITERIA`, `KAPPA_THRESHOLD`, `main` | none |

### 2. Schema fields reached by string

Required reading before touching `src/schema.py` or `src/pipeline/generate.py`.

`generate.py` is clean. `_field(requirement, name)` takes exactly three literal values, `"issue_key"`,
`"title"` and `"description"`, all naming fields on the *input* `SampledRequirement`, never on the
output decomposition. Both its branches raise on an unknown name.

`src/eval/rendering.py` is not clean. Eight `schema.py` fields are read by string key off a plain
dict through `.get()` with defaults: `epic_summary`, `user_stories`, `id`, `story`,
`acceptance_criteria`, `complexity`, `dependencies`, `source_files`. None of them raise. A rename in
`schema.py` would degrade the rendered text rather than break the run, and `rendering.py` produces
the stimulus for both the Layer 3 judge and the Layer 4 sheet, so the degraded text would become what
a rater scored with nothing on disk to say so. No test would catch it: `test_run_judge.py` and
`test_calibration_set.py` build their fixtures from the same string literals, so both drift together.

Worth doing on its own merits: have `render_decomposition` validate through
`Decomposition.model_validate` and read attributes, so the contract is enforced at the one point
where a rater-facing artefact is produced.

### 3. The one temporary measure

`scripts/run_judge.py` re-exports `scrub_artefact` with `F401` purely because
`tests/test_run_judge.py` asserts the scrubbing behaviour through that module. It is a stopgap, not a
pattern. The right fix is for the test to import from `src.eval.rendering` directly. No further
re-exports should be added.

Note the distinction from the `make_llm` / `make_judge` delegates, which are real functions that
forward and exist to preserve a monkeypatch seam. Those are deliberate and stay.

## Left alone on purpose

These look like redundancy and are not. A future pass should not remove them without reading why.

- **`src/eval/rendering.py` as a shared module.** Both the judge and the Layer 4 sheet importing the
  same renderers is the mechanism that makes "the researcher saw what the judge saw" a property of
  the code rather than a claim. Do not let either caller acquire its own copy.
- **`hybrid_retrieve` called with a one-type tuple by `retrieve_by_type`.** It looks like a wrapper
  around a wrapper. It is the reason per-type retrieval is not a second code path with its own
  self-exclusion bug. See `docs/DECISION_retrieval_budget.md` on why global top-k must not return.
- **The strict parse in `src/eval/judge.py`.** Every raise is deliberate; a defaulted verdict would
  be indistinguishable from a real one downstream.
- **Hard REAL / AMBIGUOUS / HALLUCINATED in `file_verifier.py`.** No soft category, per CLAUDE.md.
- **Judging both presentation orders and reconciling to null on disagreement.** The inconsistency
  rate is itself a reported number.
- **The confirm gates**: `sources.py` `confirm=True` for the paid summary pass, the `--force` guards
  in `freeze_requirements.py` and `build_calibration_set.py`, and
  `index.assert_codebase_summaries_complete`. Each guards something irreversible or expensive.
- **`meta()` in `seoss_loader.py`.** Uncalled, and kept: it is how a reader confirms which dump a
  result came from. Documented in CODEBASE_GUIDE.md.
- **The explicit `CONDITION_CONTEXTS` table in `conditions.py`.** Could be generated from
  `LEAVE_ONE_OUT`, but the ablation design being readable at a glance is worth six lines.
- **Rationale-carrying docstrings longer than their bodies.** See deferred item 18.
- **`results/` and `data/frozen/requirements.json`.** Published artefacts of a completed run.

## Corrections made during the work

Recorded because each was a wrong claim in an earlier version of this document. The pattern matters
more than the individual errors: static analysis consistently under-read this codebase, and every
correction came from attempting the change rather than from more analysis.

1. Item 2 was four unused imports, not five. `scrub_artefact` is reached by attribute from a test.
2. The attribute-access list was 20 names, reported as 19, then found to be 24 once string-name
   patching was included.
3. Item 8's split into 8a and 8b was wrong: the client factory needed the delegate seam, not a free
   move.
4. Item 9 had four copy sites, not three.
5. The loose frozen-file predicate keeps a bare string rather than raising on it, which is worse than
   the `TypeError` originally claimed.
6. Item 8b's delegate mutation check was specified against the wrong property and was re-run against
   the right one.
7. Item 4 was rated low risk and was in fact blocked on a test edit. It was attempted, reverted, and
   redone once the edit was approved.
