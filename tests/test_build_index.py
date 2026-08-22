"""Tests for the scope logic in scripts/build_index.py, the part that decides which files the
sanity codebase_summaries pass is allowed to spend LLM calls on. Everything else in that script is
orchestration over already-tested modules; this is the piece with a real decision in it.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from src.data.seoss_loader import SeossLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_index  # noqa: E402

from src.data.frozen import load_frozen_requirements  # noqa: E402

SCHEMA = """
CREATE TABLE issue (issue_id text NOT NULL UNIQUE, type text, summary text, description text, status text, resolution text, created_date text, resolved_date text);
CREATE TABLE code_change (commit_hash text NOT NULL, file_path text, old_file_path text, change_type text, is_deleted integer, sum_added_lines integer, sum_removed_lines integer);
"""


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "pig.sqlite"
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    rows = [
        # commitA: one main-source file that still exists, one that has since been deleted, plus a
        # non-Java file and a test-tree file that must never enter the summary scope.
        ("commitA", "src/org/apache/pig/PigServer.java"),
        ("commitA", "src/org/apache/pig/Gone.java"),
        ("commitA", "CHANGES.txt"),
        ("commitA", "test/org/apache/pig/TestPigServer.java"),
        ("commitB", "src/org/apache/pig/impl/PigContext.java"),
        ("commitB", "src/org/apache/pig/PigServer.java"),   # overlaps commitA, must not duplicate
    ]
    for commit, file_path in rows:
        conn.execute("INSERT INTO code_change (commit_hash, file_path, is_deleted) VALUES (?,?,0)",
                     (commit, file_path))
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "pig"
    for rel in ("src/org/apache/pig/PigServer.java", "src/org/apache/pig/impl/PigContext.java",
                "CHANGES.txt", "test/org/apache/pig/TestPigServer.java"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// fixture\n")
    return root


def test_sanity_scope_keeps_only_existing_main_source_java(db, repo):
    requirements = [
        {"issue_key": "PIG-1", "resolution_commit": "commitA"},
        {"issue_key": "PIG-2", "resolution_commit": "commitB"},
    ]
    with SeossLoader(db, repo) as loader:
        scope = build_index.sanity_summary_scope(loader, repo, requirements)

    assert [p.relative_to(repo).as_posix() for p in scope] == [
        "src/org/apache/pig/PigServer.java",        # deduplicated across the two commits
        "src/org/apache/pig/impl/PigContext.java",
    ]


def test_sanity_scope_skips_requirements_without_a_resolution_commit(db, repo):
    requirements = [{"issue_key": "PIG-3", "resolution_commit": None}]
    with SeossLoader(db, repo) as loader:
        assert build_index.sanity_summary_scope(loader, repo, requirements) == []


def test_frozen_requirements_drops_the_meta_header(tmp_path: Path):
    path = tmp_path / "requirements.json"
    path.write_text(json.dumps([{"_meta": {"n_frozen": 2}},
                                {"issue_key": "PIG-1"}, {"issue_key": "PIG-2"}]))
    assert [r["issue_key"] for r in load_frozen_requirements(path)] == ["PIG-1", "PIG-2"]
