"""Layer 4 researcher calibration (proposal Section 7.4). Agreement between the researcher's blinded
rankings and the LLM judge on a twenty-pair subset, via Cohen's kappa. Layer 3 is trusted as a
primary quality signal only if kappa clears the pre-registered threshold."""

from __future__ import annotations

from src.analysis.stats import cohens_kappa
from src.eval.judge import CRITERIA

KAPPA_THRESHOLD = 0.6   # substantial agreement, pre-registered

# The rating sheet's columns: the five judge criteria plus the reconciled overall winner, which is
# the figure the kappa gate is applied to. Defined here once because build_calibration_set.py writes
# this CSV and score_calibration.py reads it back. Two independent definitions would let the writer
# and the reader drift, and a drifted column name would silently drop out of every kappa rather than
# raising, which is the failure mode hardest to notice in a number that gates Layer 3.
OVERALL = "overall"
RATING_COLUMNS = (*CRITERIA, OVERALL)


def calibrate(researcher_choices: list[str], judge_choices: list[str]) -> dict:
    """Each list is the chosen option ("A"/"B" or condition label) per calibration pair, in the
    same order. Returns kappa, its CI, and whether Layer 3 is validated for primary use."""
    result = cohens_kappa(researcher_choices, judge_choices)
    result["threshold"] = KAPPA_THRESHOLD
    result["layer3_validated"] = result["kappa"] >= KAPPA_THRESHOLD
    return result
