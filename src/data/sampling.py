"""Requirement sampling protocol (proposal Section 7.1, Phase 1).

Sample twenty Apache Pig requirements, favouring issues with linked design discussions and clear
acceptance signals in their commits. Each sampled requirement carries the anchor commit for the
Layer 2 window and the assembled reference-artefact set for SQ3.

Filters are applied in a relaxation sequence (the Phase 1 contingency) so the run still reaches
twenty when the strictest filter does not yield enough:
    level 0  has design discussion AND an acceptance commit
    level 1  has an acceptance commit
    level 2  any Fixed requirement of the target type with a usable description
Each sampled item records the level it qualified at, so "how many needed relaxation" is reportable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.data.seoss_loader import SeossLoader

TARGET_N = 20
REQUIREMENT_TYPES: tuple[str, ...] = ("New Feature", "Improvement")
MIN_COMMENTS_FOR_DISCUSSION = 2


@dataclass
class SampledRequirement:
    issue_key: str
    title: str
    description: str
    resolution_commit: str | None = None        # SEOSS hash, kept for provenance
    local_commits: list[str] = field(default_factory=list)   # mapped to the clone; used by Layer 2
    reference_artefacts: list[str] = field(default_factory=list)
    relaxation_level: int = 0


def _has_discussion(loader: SeossLoader, issue_id: str) -> bool:
    if len(loader.comments(issue_id)) >= MIN_COMMENTS_FOR_DISCUSSION:
        return True
    return bool(loader.linked_issue_ids(issue_id))


def _acceptance_commit(loader: SeossLoader, issue_id: str) -> str | None:
    """Latest commit linked to the issue that actually touches code. (This SEOSS dump does not
    flag merges, so there is no merge to skip; the code-touching check is the real signal.)"""
    for c in reversed(loader.commits_for_issue(issue_id)):
        if loader.files_changed(c.commit_hash):
            return c.commit_hash
    return None


def sample_requirements(
    loader: SeossLoader,
    target_n: int = TARGET_N,
    types: tuple[str, ...] = REQUIREMENT_TYPES,
    commit_index=None,
) -> list[SampledRequirement]:
    candidates = loader.issues(types=types)   # defaults: resolution='Fixed', description floor

    # Precompute the two features once per candidate to avoid repeated DB work across levels.
    feats: dict[str, dict] = {}
    for iss in candidates:
        feats[iss.issue_id] = {
            "discussion": _has_discussion(loader, iss.issue_id),
            "commit": _acceptance_commit(loader, iss.issue_id),
        }

    predicates = [
        lambda iid: feats[iid]["discussion"] and bool(feats[iid]["commit"]),
        lambda iid: bool(feats[iid]["commit"]),
        lambda iid: True,
    ]

    selected: dict[str, SampledRequirement] = {}
    for level, pred in enumerate(predicates):
        if len(selected) >= target_n:
            break
        for iss in candidates:
            if len(selected) >= target_n:
                break
            if iss.issue_id in selected or not pred(iss.issue_id):
                continue
            local = (loader.local_anchor_commits(iss.issue_id, commit_index)
                     if commit_index is not None else [])
            selected[iss.issue_id] = SampledRequirement(
                issue_key=iss.issue_id,
                title=iss.summary or "",
                description=iss.description or "",
                resolution_commit=feats[iss.issue_id]["commit"],
                local_commits=local,
                reference_artefacts=loader.reference_artefacts(iss.issue_id),
                relaxation_level=level,
            )
    return list(selected.values())
