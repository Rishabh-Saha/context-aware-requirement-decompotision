"""Default locations, in one place.

Every script took its own copy of these strings, so `data/seoss33/pig.sqlite` appeared four times,
`data/frozen/requirements.json` five times, and the Apache Pig main-source subpath four times
including two hardcoded inside src/retrieval/sources.py. Nothing enforced that the copies agreed.
That is survivable while every script is run from the repo root against the same checkout, and it
stops being survivable the moment one of them moves, because the scripts that did not get the edit
keep reading the old location and report an empty result rather than an error.

These are defaults, not policy. Every script still exposes each one as a command-line flag, and the
values here are what a bare invocation from the repo root resolves to.

Kept deliberately separate from two things it could be confused with:

    src/eval/rendering.cell_stem   the *structure* of an archived filename, which is a contract
                                   between the run writer and its readers rather than a location
    config/config.yaml             the methodology values (models, temperature, commit window).
                                   Paths are how the code finds its inputs, not a claim about how
                                   the experiment was run, so they do not belong in the manifest.
"""

from __future__ import annotations

# -- inputs -------------------------------------------------------------------------------------
DEFAULT_CONFIG = "config/config.yaml"
DEFAULT_DB = "data/seoss33/pig.sqlite"
DEFAULT_REPO = "data/repos/pig"
DEFAULT_FROZEN = "data/frozen/requirements.json"
DEFAULT_PROMPT = "prompts/judge_pairwise.txt"

# -- outputs ------------------------------------------------------------------------------------
DEFAULT_RUNS_DIR = "data/runs"
DEFAULT_RESULTS_DIR = "results"
DEFAULT_CACHE = "data/summaries"
DEFAULT_PERSIST = "./data/chroma"
DEFAULT_COLLECTION = "seoss_pig"

# Subdirectories of a run directory. Written by one script and read by the next, which is why they
# are shared rather than redeclared: run_judge writes judge/, build_calibration_set reads it and
# writes calibration/, score_calibration reads that.
JUDGE_SUBDIR = "judge"
CALIBRATION_SUBDIR = "calibration"

# -- subpaths inside the Apache Pig clone -------------------------------------------------------
# The main source tree the codebase_summaries pass covers, and the Forrest xdocs the design_documents
# builder reads. Relative to the repo root given by DEFAULT_REPO.
SRC_SUBPATH = "src/org/apache/pig"
DOCS_SUBPATH = "src/docs/src/documentation/content/xdocs"
