"""Tests for the past_tickets/design_documents/coding_conventions builders. past_tickets uses a
fixture DB (same minimal SEOSS schema as test_seoss_loader.py); the file-backed builders run
against the real Pig clone and xdocs already checked into data/repos/pig, since those are static
fixtures in their own right.
"""

import sqlite3
from pathlib import Path

import pytest

from src.conditions import ContextType
from src.data.seoss_loader import SeossLoader
from src.retrieval.sources import (
    coding_convention_chunks,
    design_document_chunks,
    past_tickets_chunks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PIG_REPO = REPO_ROOT / "data" / "repos" / "pig"
XDOCS_DIR = PIG_REPO / "src" / "docs" / "src" / "documentation" / "content" / "xdocs"

SCHEMA = """
CREATE TABLE issue (issue_id text NOT NULL UNIQUE, type text, created_date text, resolved_date text, summary text, description text, status text, resolution text);
"""


@pytest.fixture
def loader(tmp_path: Path) -> SeossLoader:
    db_path = tmp_path / "pig.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)

    def issue(iid, typ, summary, desc, res="Fixed"):
        conn.execute(
            "INSERT INTO issue (issue_id, type, summary, description, resolved_date, status, resolution) "
            "VALUES (?,?,?,?,?,?,?)", (iid, typ, summary, desc, "2015-01-01", "Closed", res))

    # In the candidate pool: New Feature, Fixed, description over the floor.
    issue("PIG-1", "New Feature", "Add CSV storage",
          "Support CSV load and store operations in Pig scripts end to end.")
    # Wrong type -> excluded.
    issue("PIG-2", "Bug", "Fix NPE", "A null pointer exception happens when loading empty files.")
    # Not Fixed -> excluded.
    issue("PIG-3", "Improvement", "Speed up join", "Make the join operator faster on large inputs.",
          res="Won't Fix")
    # Contains Jira markup that should be stripped.
    issue("PIG-4", "Improvement", "Kerberos local mode bug",
          "It fails in local mode.\n{noformat}\npig -x local script.pig\n{noformat}\nSee https://issues.apache.org/jira/browse/PIG-4 for details.")

    conn.commit()
    conn.close()
    return SeossLoader(db_path)


def test_past_tickets_chunks_filters_by_type_and_resolution(loader):
    chunks = past_tickets_chunks(loader)
    ids = {c.id for c in chunks}
    assert ids == {"past_ticket::PIG-1", "past_ticket::PIG-4"}
    for c in chunks:
        assert c.context_type is ContextType.PAST_TICKETS
        assert c.metadata["issue_id"] in {"PIG-1", "PIG-4"}


def test_past_tickets_chunks_strips_jira_markup(loader):
    chunks = {c.id: c for c in past_tickets_chunks(loader)}
    text = chunks["past_ticket::PIG-4"].text
    assert "{noformat" not in text
    assert "https://" not in text
    assert "It fails in local mode." in text


@pytest.mark.skipif(not XDOCS_DIR.exists(), reason="Pig clone not present in this environment")
def test_design_document_chunks_parses_all_content_files():
    chunks = design_document_chunks(XDOCS_DIR)
    ids = {c.id for c in chunks}
    # site.xml/tabs.xml are nav-only and yield no chunk; the rest of the 15 xdocs files do.
    assert "design_doc::site" not in ids
    assert "design_doc::tabs" not in ids
    assert "design_doc::cont" in ids
    # These four previously failed to parse due to undeclared HTML entities.
    for stem in ("basic", "func", "pig-index", "udf"):
        assert f"design_doc::{stem}" in ids
    for c in chunks:
        assert c.context_type is ContextType.DESIGN_DOCS
        assert c.text.strip()


@pytest.mark.skipif(not PIG_REPO.exists(), reason="Pig clone not present in this environment")
def test_coding_convention_chunks_reads_checkstyle_and_readme():
    chunks = {c.id: c for c in coding_convention_chunks(PIG_REPO)}
    assert set(chunks) == {"coding_convention::checkstyle", "coding_convention::readme"}
    for c in chunks.values():
        assert c.context_type is ContextType.CODING_CONVENTIONS
        assert c.text.strip()
