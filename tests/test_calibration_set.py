"""Tests for scripts/build_calibration_set.py.

The sampling has to be reproducible from the recorded seed, spread the way the design says, and
above all give away nothing. The blinding assertions are the important ones here: if a condition
name, the reference sentinel or a judge verdict reaches the rating sheet, Layer 4 measures nothing,
and no later test would notice.
"""

import json
import sys
from pathlib import Path

import pytest

from src.conditions import Condition
from src.eval.comparisons import REFERENCE, comparison_types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_calibration_set as bcs  # noqa: E402

ISSUES = [f"PIG-{600 + i}" for i in range(20)]


def decomposition(issue: str, condition: str) -> dict:
    return {
        "epic_summary": f"Epic for {issue}",
        "user_stories": [
            {
                "id": "US-1",
                "story": f"As a user, I want {issue} handled, so that the job runs.",
                "acceptance_criteria": [f"{issue} behaves as described"],
                "complexity": "M",
                "dependencies": [],
                "source_files": ["src/org/apache/pig/PigServer.java"],
            },
        ],
    }


def judgment(issue: str, left: str, right: str, sq: str, inconsistent: bool = False) -> dict:
    winner = None if inconsistent else right
    return {
        "run_id": "RUN1",
        "issue_key": issue,
        "left": left,
        "right": right,
        "sub_question": sq,
        "winner": winner,
        "positional_inconsistent": inconsistent,
        "per_criterion_winner": {c: winner for c in bcs.CRITERIA},
        "per_criterion_inconsistent": [],
    }


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    """A complete judge pass on disk: 20 requirements times the seven comparison types."""
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "data" / "runs" / "RUN1"
    run_dir.mkdir(parents=True)

    frozen = [{"_meta": {"frozen_at": "2026-01-01T00:00:00+00:00"}}]
    for issue in ISSUES:
        frozen.append({
            "issue_key": issue,
            "title": f"title for {issue}",
            "description": f"description for {issue}",
            "reference_artefacts": [f"{issue} human authored artefact text.\n\n"
                                    "git-svn-id: https://svn.apache.org/repos/asf/x@1 13f79535"],
        })
        for condition in Condition:
            (run_dir / f"{issue}__{condition.value}.json").write_text(json.dumps({
                "decomposition": decomposition(issue, condition.value),
            }))
    frozen_path = tmp_path / "data" / "frozen" / "requirements.json"
    frozen_path.parent.mkdir(parents=True)
    frozen_path.write_text(json.dumps(frozen))

    judge_dir = run_dir / "judge"
    judge_dir.mkdir()
    rows = []
    for i, issue in enumerate(ISSUES):
        for j, ct in enumerate(comparison_types()):
            # A minority are positionally inconsistent, so the decided-preference has something to
            # prefer over.
            rows.append(judgment(issue, ct.left, ct.right, ct.sub_question,
                                 inconsistent=(i + j) % 9 == 0))
    (judge_dir / "judgments.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n"
    )
    return tmp_path


def build(monkeypatch, *extra: str) -> int:
    monkeypatch.setattr(sys, "argv", ["build_calibration_set.py", "--run-id", "RUN1", *extra])
    return bcs.main()


def cal_dir(workspace: Path) -> Path:
    return workspace / "data" / "runs" / "RUN1" / "calibration"


def sheet_rows(workspace: Path) -> list[dict]:
    path = cal_dir(workspace) / "sheet.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- stratification

def test_stratum_targets_follow_the_design_and_sum_to_n():
    # Seven comparison types in a 4:1:2 split, so twenty pairs divide 11 / 3 / 6.
    assert bcs.stratum_targets(20, bcs.DESIGN_WEIGHTS) == {"SQ1": 11, "SQ2": 3, "SQ3": 6}
    for n in (7, 14, 20, 21, 33):
        targets = bcs.stratum_targets(n, bcs.DESIGN_WEIGHTS)
        assert sum(targets.values()) == n


def test_sample_is_stratified_and_prefers_decided(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    keys = json.loads((cal_dir(workspace) / "key.json").read_text())

    assert len(keys) == 20
    counts = {}
    for row in keys.values():
        counts[row["sub_question"]] = counts.get(row["sub_question"], 0) + 1
    assert counts == {"SQ1": 11, "SQ2": 3, "SQ3": 6}
    # The decided pool is large enough here, so nothing inconsistent should have been drawn.
    assert all(not row["judge_positional_inconsistent"] for row in keys.values())
    assert all(row["judge_winner"] is not None for row in keys.values())


def test_sample_is_spread_across_requirements(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    keys = json.loads((cal_dir(workspace) / "key.json").read_text())

    issues = [row["issue_key"] for row in keys.values()]
    # Twenty pairs drawn round-robin over twenty requirements should touch most of the corpus, not
    # cluster into a handful of issues.
    assert len(set(issues)) >= 12
    assert max(issues.count(i) for i in set(issues)) <= 3


# ---------------------------------------------------------------- determinism

def test_same_seed_reproduces_the_draw(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    first_keys = json.loads((cal_dir(workspace) / "key.json").read_text())
    first_sheet = sheet_rows(workspace)

    assert build(monkeypatch, "--force") == 0
    assert json.loads((cal_dir(workspace) / "key.json").read_text()) == first_keys
    assert sheet_rows(workspace) == first_sheet


def test_different_seed_changes_the_draw(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    first = json.loads((cal_dir(workspace) / "key.json").read_text())

    assert build(monkeypatch, "--force", "--seed", "999") == 0
    second = json.loads((cal_dir(workspace) / "key.json").read_text())

    def identity(keys):
        return {(r["issue_key"], r["comparison_left"], r["comparison_right"]) for r in keys.values()}

    assert identity(first) != identity(second)


def test_seed_is_recorded_in_the_manifest(workspace, monkeypatch):
    assert build(monkeypatch, "--seed", "4242") == 0
    manifest = json.loads((cal_dir(workspace) / "manifest.json").read_text())
    assert manifest["seed"] == 4242
    assert manifest["strata"]["SQ1"]["target"] == 11
    assert manifest["rating_columns"] == [*bcs.CRITERIA, "overall"]


# ---------------------------------------------------------------- blinding

def test_rater_facing_files_contain_no_blinded_labels(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    directory = cal_dir(workspace)

    # Condition names and provenance tells must not appear anywhere in a rater-facing file.
    hard_forbidden = [c.value for c in Condition] + ["git-svn-id", "judge", "ablation"]
    for name in ("sheet.jsonl", "sheet.md", "calibration_ratings.csv"):
        text = (directory / name).read_text().lower()
        for token in hard_forbidden:
            assert token not in text, f"{token!r} leaked into {name}"

    # The reference sentinel and the word winner are checked against the rated content only. The
    # sheet's fixed instructions legitimately define project_specificity in terms of "references",
    # and that wording is identical for every pair, so it identifies nothing.
    sheet_md = (directory / "sheet.md").read_text()
    rated_content = sheet_md.split("---", 1)[1].lower()
    for token in (REFERENCE, "winner", "condition"):
        assert token not in rated_content, f"{token!r} leaked into the rated content"
    assert REFERENCE not in (directory / "sheet.jsonl").read_text().lower()


def test_sheet_carries_only_the_four_blinded_fields(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    for row in sheet_rows(workspace):
        assert set(row) == {"pair_id", "requirement", "output_a", "output_b"}
        assert row["output_a"] and row["output_b"]


def test_key_is_complete_and_matches_the_sheet(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    keys = json.loads((cal_dir(workspace) / "key.json").read_text())
    sheet = sheet_rows(workspace)

    assert {r["pair_id"] for r in sheet} == set(keys)
    for pair_id, row in keys.items():
        # Whichever way the coin fell, the two sheet slots hold exactly the comparison's two sides.
        assert {row["sheet_a"], row["sheet_b"]} == {row["comparison_left"], row["comparison_right"]}
        assert row["sheet_a"] != row["sheet_b"]


def test_sheet_order_is_randomised_relative_to_the_comparison(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    keys = json.loads((cal_dir(workspace) / "key.json").read_text())
    swapped = sum(1 for row in keys.values() if row["sheet_a"] == row["comparison_right"])
    # A fresh coin flip per pair, so neither orientation should account for all twenty.
    assert 0 < swapped < len(keys)


def test_reference_side_is_scrubbed_on_the_sheet(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    keys = json.loads((cal_dir(workspace) / "key.json").read_text())
    sheet = {row["pair_id"]: row for row in sheet_rows(workspace)}

    sq3 = [pid for pid, row in keys.items() if REFERENCE in (row["sheet_a"], row["sheet_b"])]
    assert sq3, "the sample should include SQ3 pairs"
    for pair_id in sq3:
        row = keys[pair_id]
        # Only the reference side is scrubbed. The generated side is shown as the model wrote it,
        # so the assertion targets the slot the reference actually occupies on this sheet.
        slot = "output_a" if row["sheet_a"] == REFERENCE else "output_b"
        reference_text = sheet[pair_id][slot]
        assert "git-svn-id" not in reference_text
        assert row["issue_key"] not in reference_text
        assert "human authored artefact text" in reference_text, "substance must survive scrubbing"


# ---------------------------------------------------------------- guards

def test_existing_ratings_are_not_silently_overwritten(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    ratings = cal_dir(workspace) / "calibration_ratings.csv"
    ratings.write_text(ratings.read_text().replace("pair_01,,,,,,", "pair_01,A,A,A,A,A,A"))

    with pytest.raises(SystemExit, match="already exists"):
        build(monkeypatch)
    assert "pair_01,A,A,A,A,A,A" in ratings.read_text(), "ratings must survive the refusal"


def test_ratings_csv_has_a_row_per_pair_and_a_column_per_criterion(workspace, monkeypatch):
    assert build(monkeypatch) == 0
    lines = (cal_dir(workspace) / "calibration_ratings.csv").read_text().strip().splitlines()

    assert lines[0] == "pair_id," + ",".join([*bcs.CRITERIA, "overall"])
    assert len(lines) == 21          # header plus twenty pairs
    assert all(line.endswith(",,,,,,") for line in lines[1:]), "cells start empty"
