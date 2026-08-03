# Context-Aware Requirements Decomposition with Retrieval-Augmented LLMs

Codebase for the MSc thesis. A RAG pipeline decomposes Apache Pig (SEOSS 33) business requirements
into developer-ready user stories, evaluated by a four-layer framework. See the proposal for the
full design and `CLAUDE.md` for the working context.

## Layout
- `src/schema.py` fixed decomposition JSON contract
- `src/conditions.py` six ablation conditions, four context types
- `src/retrieval/` chunking, RRF fusion, ChromaDB index, hybrid retrieval
- `src/pipeline/` prompt assembly and per-condition generation
- `src/eval/` Layer 1 structural, Layer 2 file verifier, Layer 3 judge + comparisons, Layer 4 calibration
- `src/analysis/stats.py` Wilcoxon, rank-biserial, Holm-Bonferroni, Cohen's kappa
- `prompts/` decomposition and pairwise-judge templates
- `config/config.yaml` central config, secrets in `.env`

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in keys
pytest                  # implemented modules should pass
```

## Status
Deterministic core is implemented and tested: schema, conditions, RRF, structural metrics, file
verifier (REAL / AMBIGUOUS / HALLUCINATED with commit-window checking), comparison-pair generation,
and the analysis statistics. Data-dependent and API-dependent stages (SEOSS loading and sampling,
index building, hybrid retrieval, generation, the judge call) are scaffolded with interfaces and
TODOs, to be completed against real data.
