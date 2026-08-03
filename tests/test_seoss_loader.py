"""Tests for the SEOSS loader and sampling, against a fixture DB built from the real SEOSS 33
schema (the exact CREATE TABLE statements from the Pig dump)."""

import sqlite3
from pathlib import Path

import pytest

from src.data.seoss_loader import SeossLoader
from src.data.sampling import sample_requirements

SCHEMA = """
CREATE TABLE meta (key text NOT NULL, value text NOT NULL);
CREATE TABLE issue (issue_id text NOT NULL UNIQUE, type text, created_date text, created_date_zoned text, updated_date text, updated_date_zoned text, resolved_date text, resolved_date_zoned text, summary text, description text, priority text, status text, resolution text, assignee text, assignee_username text, reporter text, reporter_username text);
CREATE TABLE issue_component (issue_id text NOT NULL, component text NOT NULL);
CREATE TABLE issue_fix_version (issue_id text NOT NULL, fix_version text NOT NULL);
CREATE TABLE issue_comment (issue_id text NOT NULL, username text, display_name text, created_date text, created_date_zoned text, message text);
CREATE TABLE issue_link (source_issue_id text NOT NULL, target_issue_id text NOT NULL, name text, outward_label text, is_containment integer);
CREATE TABLE change_set (commit_hash text NOT NULL UNIQUE, committed_date text, committed_date_zoned text, message text, author text, author_email text, is_merge integer);
CREATE TABLE change_set_link (commit_hash text NOT NULL, issue_id text NOT NULL);
CREATE TABLE code_change (commit_hash text NOT NULL, file_path text, old_file_path text, change_type text, is_deleted integer, sum_added_lines integer, sum_removed_lines integer);
"""


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "pig.sqlite"
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)

    def issue(iid, typ, summary, desc, resolved="2015-01-02", status="Closed", res="Fixed"):
        conn.execute(
            "INSERT INTO issue (issue_id, type, summary, description, resolved_date, status, resolution) "
            "VALUES (?,?,?,?,?,?,?)", (iid, typ, summary, desc, resolved, status, res))

    # PIG-1: feature, has discussion (2 comments) + acceptance commit -> level 0
    issue("PIG-1", "New Feature", "Add CSV storage", "Support CSV load and store operations in Pig scripts.")
    conn.execute("INSERT INTO issue_comment (issue_id, message) VALUES (?,?)", ("PIG-1", "design note a"))
    conn.execute("INSERT INTO issue_comment (issue_id, message) VALUES (?,?)", ("PIG-1", "design note b"))
    conn.execute("INSERT INTO issue_link VALUES (?,?,?,?,?)", ("PIG-1", "PIG-1a", "sub", "contains", 1))
    issue("PIG-1a", "Sub-task", "CSV writer", "Implement the writer.")
    conn.execute("INSERT INTO change_set (commit_hash, committed_date, message, is_merge) "
                 "VALUES (?,?,?,?)", ("commitA", "2015-01-01", "PIG-1 add CSV storage", 0))
    conn.execute("INSERT INTO change_set (commit_hash, committed_date, message, is_merge) "
                 "VALUES (?,?,?,?)", ("mergeM", "2015-01-02", "Merge branch", 1))
    conn.execute("INSERT INTO change_set_link VALUES (?,?)", ("commitA", "PIG-1"))
    conn.execute("INSERT INTO change_set_link VALUES (?,?)", ("mergeM", "PIG-1"))
    conn.execute("INSERT INTO code_change (commit_hash, file_path, change_type, is_deleted) "
                 "VALUES (?,?,?,?)", ("commitA", "src/org/apache/pig/CSVStorage.java", "ADD", 0))

    # PIG-2: feature, no discussion, no commit -> only qualifies at level 2
    issue("PIG-2", "Improvement", "Improve parser", "Make the parser faster and lower its memory footprint.")

    # PIG-3: a Bug -> excluded by type filter
    issue("PIG-3", "Bug", "Null pointer", "Crashes on empty input.")

    # PIG-4: a feature that was NOT Fixed (Won't Fix) -> excluded by resolution filter
    issue("PIG-4", "New Feature", "Future work", "Was declined by the team.", res="Won't Fix")

    # PIG-5: Fixed feature but description too short -> excluded by the description floor
    issue("PIG-5", "New Feature", "Tiny", "short")

    conn.commit()
    conn.close()
    return path


def test_type_resolution_and_description_filters(db):
    with SeossLoader(db) as loader:
        ids = {i.issue_id for i in loader.issues(types=("New Feature", "Improvement"))}
    # PIG-3 excluded (Bug), PIG-4 excluded (not Fixed), PIG-5 excluded (description too short)
    assert ids == {"PIG-1", "PIG-2"}


def test_commit_for_issue_prefers_code_touching(db):
    # mergeM is the latest linked commit but touches no code; commitA does, so it anchors.
    with SeossLoader(db) as loader:
        assert loader.commit_for_issue("PIG-1") == "commitA"
        assert loader.files_changed("commitA") == ["src/org/apache/pig/CSVStorage.java"]


def test_reference_artefacts_assembled(db):
    with SeossLoader(db) as loader:
        refs = loader.reference_artefacts("PIG-1")
    joined = "\n".join(refs)
    assert "Support CSV load and store" in joined       # own description
    assert "Implement the writer." in joined            # linked sub-task
    assert "PIG-1 add CSV storage" in joined            # commit message


def test_sampling_relaxation_levels(db):
    with SeossLoader(db) as loader:
        sampled = sample_requirements(loader, target_n=20)
    by_key = {s.issue_key: s for s in sampled}
    assert by_key["PIG-1"].relaxation_level == 0        # discussion + acceptance commit
    assert by_key["PIG-1"].resolution_commit == "commitA"
    assert by_key["PIG-2"].relaxation_level == 2        # only qualifies when filters fully relaxed


def test_sampling_respects_target_n(db):
    with SeossLoader(db) as loader:
        assert len(sample_requirements(loader, target_n=1)) == 1
