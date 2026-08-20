# Context-Aware Requirements Decomposition with Retrieval-Augmented LLMs

Codebase for the MSc thesis of the same name (Liverpool John Moores University). A RAG pipeline
decomposes Apache Pig (SEOSS 33) business requirements into developer-ready user stories, and a
four-layer framework evaluates the outputs.

**Status: the experiment is complete.** All six conditions were run across the twenty frozen
requirements on run `20260814T033139Z`, giving 120 decompositions and 140 reconciled pairwise
comparisons. The final numbers reported in the thesis are recorded in
[RESULTS.md](RESULTS.md), and the artefacts behind each thesis table are listed in
[results/README.md](results/README.md). `CLAUDE.md` holds the working context and the
methodology rules that must not be regressed.

## Headline findings

Retrieval significantly reduced file-reference hallucination (0.703 to 0.496, Wilcoxon p = 0.039,
rank-biserial 0.57) but produced no measurable gain in judged quality. No individual context
category showed a significant contribution after Holm-Bonferroni correction. The pairwise judge
failed its pre-registered calibration gate (Cohen's kappa = 0.56 against a threshold of 0.60), so
Layer 3 is reported descriptively and Layers 1 and 2 carry the primary conclusions. These are
case-study findings on a single project.

## Layout

- `src/schema.py` fixed decomposition JSON contract
- `src/conditions.py` six ablation conditions, four context types
- `src/data/` SEOSS loader, requirement sampling, SEOSS-to-clone commit resolver
- `src/retrieval/` chunking, RRF fusion, ChromaDB index, hybrid and per-type retrieval
- `src/pipeline/` prompt assembly and per-condition generation
- `src/eval/` Layer 1 structural, Layer 2 file verifier, Layer 3 judge and comparisons, Layer 4 calibration
- `src/analysis/stats.py` Wilcoxon, rank-biserial, Holm-Bonferroni, Cohen's kappa
- `scripts/` experiment runner, judge runner, calibration build and scoring
- `prompts/` decomposition and pairwise-judge templates
- `config/config.yaml` central config, secrets in `.env`
- `data/frozen/` the frozen twenty-requirement sample and other committed inputs
- `results/` final run artefacts (see `results/README.md`)
- `docs/` signed decision records for design choices taken during the study

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in provider keys
pytest
```

Reproduction additionally requires the SEOSS 33 Apache Pig SQLite dump and a local clone of
`apache/pig`, neither of which is committed. Paths are set in `config/config.yaml`. Provenance and
the three-leg verification of the clone are documented in [DATA_PROVENANCE.md](DATA_PROVENANCE.md).

## Reproducing the reported run

Run identifier: `20260814T033139Z`. Generator GPT-4o at temperature 0.0; the judge runs on a
different model family, enforced in code. Prompt templates are stamped by SHA-256 with each
generation, so any change to a template is visible in the output.

```bash
# 1. Freeze the requirement sample (already committed under data/frozen/)
python scripts/build_sample.py

# 2. Build the four context indexes, including the full codebase-summaries pass
python scripts/build_indexes.py

# 3. Generate 120 decompositions and compute Layers 1 and 2 per cell
python scripts/run_experiment.py --run-id 20260814T033139Z

# 4. Layer 3: 140 pairwise comparisons, both presentation orders, reconciled
python scripts/run_judge.py --run-id 20260814T033139Z

# 5. Layer 4: build the blinded calibration sheet, rate it by hand, then score it
python scripts/build_calibration_set.py --run-id 20260814T033139Z
python scripts/score_calibration.py --run-id 20260814T033139Z
```

Steps 3 and 4 call paid model APIs and are not deterministic across providers or model versions.
Steps 1, 2 and 5 are deterministic given the same inputs.

## Data policy

`data/` is Git-ignored apart from the frozen inputs, and intermediate indexes and per-cell prompt
payloads are not committed. The aggregate artefacts needed to substantiate the thesis tables are
committed under `results/` and indexed in `results/README.md`.

## Licence and citation

Academic work submitted for the MSc programme at Liverpool John Moores University. Apache Pig data
originates from the SEOSS 33 dataset (Rath and Mader, 2019), which carries its own licence terms.