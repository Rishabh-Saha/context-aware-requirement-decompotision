import subprocess
from pathlib import Path

import pytest

from src.eval.file_verifier import FileStatus, FileVerifier, normalize_path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@t.dev")
    git("config", "user.name", "t")
    for rel in [
        "src/org/apache/pig/PigServer.java",
        "src/org/apache/pig/impl/PigContext.java",
        "README.md",
    ]:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("// stub\n")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return tmp_path


def test_real(repo):
    v = FileVerifier(repo)
    assert v.check("src/org/apache/pig/PigServer.java").status is FileStatus.REAL


def test_ambiguous_partial_path(repo):
    v = FileVerifier(repo)
    assert v.check("pig/impl/PigContext.java").status is FileStatus.AMBIGUOUS


def test_ambiguous_basename_wrong_dir(repo):
    v = FileVerifier(repo)
    assert v.check("com/example/PigServer.java").status is FileStatus.AMBIGUOUS


def test_hallucinated(repo):
    v = FileVerifier(repo)
    assert v.check("src/org/apache/pig/Ghost.java").status is FileStatus.HALLUCINATED


def test_report_rates(repo):
    v = FileVerifier(repo)
    rep = v.verify([
        "src/org/apache/pig/PigServer.java",   # REAL
        "impl/PigContext.java",                # AMBIGUOUS
        "does/not/Exist.java",                 # HALLUCINATED
    ])
    assert rep.total == 3
    assert rep.counts["REAL"] == 1
    assert rep.counts["AMBIGUOUS"] == 1
    assert rep.counts["HALLUCINATED"] == 1


def test_commit_window(repo):
    # A file added in a later commit should count REAL when the window includes that commit.
    def git(*a):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    (repo / "src/org/apache/pig/NewFile.java").write_text("// new\n")
    git("add", "-A")
    git("commit", "-q", "-m", "add NewFile")
    v = FileVerifier(repo, refs=["HEAD~1", "HEAD"])
    assert v.check("src/org/apache/pig/NewFile.java").status is FileStatus.REAL


def test_normalize():
    assert normalize_path("./a\\b.java") == "a/b.java"
