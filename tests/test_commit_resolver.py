"""Tests for SEOSS->local commit resolution. Builds a temp repo whose commits carry known
subjects/authors/dates, then resolves 'SEOSS-style' metadata (different hash, same metadata) to the
real local hashes, including the duplicate-subject case seen in Pig (e.g. PIG-692)."""

import os
import subprocess
from pathlib import Path

import pytest

from src.data.commit_resolver import LocalCommitIndex


import uuid

def _commit(repo: Path, subject: str, email: str, iso_date: str) -> str:
    (repo / "f.txt").write_text(f"{subject} {uuid.uuid4()}")   # unique content -> always a diff
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": f"{iso_date}T12:00:00",
        "GIT_COMMITTER_DATE": f"{iso_date}T12:00:00",
        "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_EMAIL": email,
        "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
    }
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", subject],
                   check=True, capture_output=True, env=env)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True, capture_output=True)
    shas = {
        "pig1_old": _commit(tmp_path, "PIG-1 add feature", "a@apache.org", "2009-01-01"),
        "pig1_new": _commit(tmp_path, "PIG-1 add feature", "a@apache.org", "2015-06-01"),  # dup subject
        "pig2": _commit(tmp_path, "PIG-2 fix parser bug", "b@apache.org", "2010-02-02"),
    }
    return tmp_path, shas


def test_exact_subject_with_date_disambiguation(repo):
    path, shas = repo
    idx = LocalCommitIndex(path)
    got = idx.resolve("PIG-1 add feature", "a@apache.org", "2015-06-02")
    assert got == [shas["pig1_new"]]


def test_duplicate_subject_without_date_returns_all(repo):
    path, shas = repo
    idx = LocalCommitIndex(path)
    got = set(idx.resolve("PIG-1 add feature", "a@apache.org", None))
    assert got == {shas["pig1_old"], shas["pig1_new"]}


def test_jira_key_fallback(repo):
    path, shas = repo
    idx = LocalCommitIndex(path)
    got = idx.resolve("mentions PIG-2 somewhere", None, None)
    assert got == [shas["pig2"]]


def test_no_match_returns_empty(repo):
    path, _ = repo
    idx = LocalCommitIndex(path)
    assert idx.resolve("PIG-999 does not exist", None, None) == []
