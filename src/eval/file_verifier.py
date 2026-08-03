"""Layer 2: programmatic file-existence verification (proposal Section 7.4).

Every source-file reference the LLM produces is checked against the Apache Pig repository and
classified into exactly one of three hard categories:

    REAL          the path exists in the repository
    AMBIGUOUS     only a partial match exists (right filename, wrong or incomplete path)
    HALLUCINATED  no match of any kind exists

This replaces the LLM-based "plausible" judgement tried in preparatory work, which collapsed
these distinctions into one soft bucket. The categories here are computed against a real Git
tree, so the grounding signal is reproducible.

Commit window. Files get added, moved, and deleted over a project's life, so verifying against a
single snapshot risks marking a genuine reference HALLUCINATED just because it existed at a
slightly different point in history. Following the Phase 2 contingency, the verifier takes a window
of commits around each requirement's resolution and treats a reference as REAL if it exists in any
commit in that window. Build the verifier with `from_commit_window(...)` to get that behaviour, or
pass an explicit list of refs.

This layer measures grounding, not task quality. A decomposition full of REAL files can still be a
poor decomposition. Keep it reported separately from the Layer 3 quality signal.
"""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable


class FileStatus(str, Enum):
    REAL = "REAL"
    AMBIGUOUS = "AMBIGUOUS"
    HALLUCINATED = "HALLUCINATED"


@dataclass(frozen=True)
class FileCheck:
    candidate: str
    normalized: str
    status: FileStatus
    matched_paths: tuple[str, ...] = ()   # supporting tracked paths (for AMBIGUOUS/REAL)


@dataclass
class VerificationReport:
    checks: list[FileCheck] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def counts(self) -> dict[str, int]:
        c = Counter(chk.status.value for chk in self.checks)
        return {s.value: c.get(s.value, 0) for s in FileStatus}

    def rate(self, status: FileStatus) -> float:
        return (self.counts[status.value] / self.total) if self.total else 0.0

    def summary(self) -> dict:
        return {
            "total": self.total,
            "real_rate": round(self.rate(FileStatus.REAL), 4),
            "ambiguous_rate": round(self.rate(FileStatus.AMBIGUOUS), 4),
            "hallucinated_rate": round(self.rate(FileStatus.HALLUCINATED), 4),
            "counts": self.counts,
        }


def normalize_path(raw: str) -> str:
    p = raw.strip().strip("`\"'").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _run_git(repo_path: Path, args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"git {' '.join(args)} failed: {exc.stderr.strip()}") from exc
    return out.stdout


def resolve_commit_window(repo_path: str | Path, around_ref: str, before: int = 2, after: int = 2) -> list[str]:
    """Return commit shas in a window around `around_ref`: `before` ancestors and `after`
    descendants, inclusive of the anchor. `after` is best-effort since descendants are only
    discoverable if a later ref is reachable; ancestors are always available."""
    repo_path = Path(repo_path)
    ancestors = _run_git(
        repo_path, ["log", "--format=%H", f"-{before + 1}", around_ref]
    ).split()
    descendants: list[str] = []
    if after > 0:
        # Commits that have `around_ref` as an ancestor, nearest first.
        raw = _run_git(
            repo_path,
            ["rev-list", "--reverse", "--ancestry-path", f"{around_ref}..HEAD"],
        ).split()
        descendants = raw[:after]
    # Anchor is included in ancestors[0]; dedupe while preserving order.
    seen: dict[str, None] = {}
    for sha in ancestors + descendants:
        seen.setdefault(sha, None)
    return list(seen)


class FileVerifier:
    """Loads the union of tracked paths across one or more refs, then classifies candidates."""

    def __init__(self, repo_path: str | Path, refs: Iterable[str] | str = "HEAD"):
        self.repo_path = Path(repo_path)
        if isinstance(refs, str):
            refs = [refs]
        self.refs = list(refs)
        if not self.repo_path.exists():
            raise FileNotFoundError(f"repo_path does not exist: {self.repo_path}")
        self._tracked: set[str] = set()
        for ref in self.refs:
            self._tracked |= self._load_tree(ref)
        self._by_basename: dict[str, list[str]] = defaultdict(list)
        for path in self._tracked:
            self._by_basename[path.rsplit("/", 1)[-1]].append(path)

    @classmethod
    def from_commit_window(cls, repo_path, around_ref, before: int = 2, after: int = 2) -> "FileVerifier":
        refs = resolve_commit_window(repo_path, around_ref, before=before, after=after)
        return cls(repo_path, refs or [around_ref])

    @classmethod
    def from_anchors(cls, repo_path, anchors, before: int = 2, after: int = 2) -> "FileVerifier":
        """Union the commit windows around several local anchor commits (see loader
        local_anchor_commits). Used when a SEOSS commit maps to more than one local hash."""
        refs: list[str] = []
        for a in anchors:
            refs.extend(resolve_commit_window(repo_path, a, before=before, after=after))
        seen: dict[str, None] = {}
        for r in refs:
            seen.setdefault(r, None)
        return cls(repo_path, list(seen) or list(anchors))

    def _load_tree(self, ref: str) -> set[str]:
        out = _run_git(self.repo_path, ["ls-tree", "-r", "--name-only", ref])
        return {normalize_path(line) for line in out.splitlines() if line.strip()}

    @property
    def tracked_count(self) -> int:
        return len(self._tracked)

    def check(self, candidate: str) -> FileCheck:
        norm = normalize_path(candidate)
        base = norm.rsplit("/", 1)[-1]

        if norm in self._tracked:
            return FileCheck(candidate, norm, FileStatus.REAL, (norm,))

        # Partial match -> AMBIGUOUS. Prefer a unique trailing sub-path match, fall back to
        # any file sharing the basename. Both are "partial path match" in the proposal's terms.
        if "/" in norm:
            suffix = tuple(p for p in self._by_basename.get(base, []) if p.endswith("/" + norm))
            if suffix:
                return FileCheck(candidate, norm, FileStatus.AMBIGUOUS, suffix)
        basename_hits = tuple(self._by_basename.get(base, []))
        if basename_hits:
            return FileCheck(candidate, norm, FileStatus.AMBIGUOUS, basename_hits)

        return FileCheck(candidate, norm, FileStatus.HALLUCINATED, ())

    def verify(self, candidates: Iterable[str]) -> VerificationReport:
        return VerificationReport([self.check(c) for c in candidates])
