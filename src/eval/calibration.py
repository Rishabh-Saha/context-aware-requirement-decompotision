"""Layer 4 researcher calibration (proposal Section 7.4). Agreement between the researcher's blinded
rankings and the LLM judge on a twenty-pair subset, via Cohen's kappa. Layer 3 is trusted as a
primary quality signal only if kappa clears the pre-registered threshold."""

from __future__ import annotations

from src.analysis.stats import cohens_kappa

KAPPA_THRESHOLD = 0.6   # substantial agreement, pre-registered


def calibrate(researcher_choices: list[str], judge_choices: list[str]) -> dict:
    """Each list is the chosen option ("A"/"B" or condition label) per calibration pair, in the
    same order. Returns kappa, its CI, and whether Layer 3 is validated for primary use."""
    result = cohens_kappa(researcher_choices, judge_choices)
    result["threshold"] = KAPPA_THRESHOLD
    result["layer3_validated"] = result["kappa"] >= KAPPA_THRESHOLD
    return result
