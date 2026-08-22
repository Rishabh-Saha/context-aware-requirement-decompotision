"""Map SEOSS `change_set` commits to commits in the local Apache Pig clone.

SEOSS built its commit table from a different git conversion of Pig than today's GitHub mirror, so
the hashes do not line up even though every commit is present. Layer 2 verifies against the local
clone, so each SEOSS commit must be resolved to its local twin by stable metadata rather than hash.

Matching strategy, most specific first:
    1. exact commit-subject match (the first line of the message)
    2. if that misses, fall back to any local commit whose subject carries the same Jira key
Candidates are then narrowed by author email and by committed-date proximity. When more than one
local commit still matches (Pig sometimes has duplicates of the same change), all are returned, and
the Layer 2 window simply spans them, which is more faithful than picking one arbitrarily.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.utils.sequences import dedupe

_JIRA_KEY = re.compile(r"[A-Z][A-Z0-9]+-\d+")
_NUL = "\x00"


@dataclass(frozen=True)
class LocalCommit:
    sha: str
    author_email: str
    committed_iso: str
    subject: str


def _subject(message: str | None) -> str:
    if not message or not message.strip():
        return ""
    return message.strip().splitlines()[0].strip()


def _as_date(s: str | None) -> date | None:
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


class LocalCommitIndex:
    """Loads every local commit once and indexes it by subject and by Jira key for fast resolve."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path)
        self._by_subject: dict[str, list[LocalCommit]] = {}
        self._by_key: dict[str, list[LocalCommit]] = {}
        self._load()

    def _load(self) -> None:
        out = subprocess.run(
            ["git", "-C", str(self.repo_path), "log", "--all",
             "--format=%H%x00%ae%x00%cI%x00%s"],   # %x00 -> git writes NULs into the output
            capture_output=True, text=True, check=True,
        ).stdout
        for line in out.splitlines():
            parts = line.split(_NUL)
            if len(parts) != 4:
                continue
            sha, ae, ci, subj = parts
            lc = LocalCommit(sha, ae.strip(), ci.strip(), subj.strip())
            self._by_subject.setdefault(lc.subject, []).append(lc)
            for key in _JIRA_KEY.findall(subj):
                self._by_key.setdefault(key, []).append(lc)

    def resolve(self, message: str | None, author_email: str | None = None,
                committed_date: str | None = None, max_days: int = 3) -> list[str]:
        subj = _subject(message)
        candidates: list[LocalCommit] = list(self._by_subject.get(subj, []))

        if not candidates:                       # fallback: match by Jira key in the message
            candidates = dedupe(
                (lc for key in _JIRA_KEY.findall(message or "")
                 for lc in self._by_key.get(key, [])),
                key=lambda lc: lc.sha,
            )
        if not candidates:
            return []

        if author_email:
            ae = author_email.strip().lower()
            narrowed = [c for c in candidates if c.author_email.lower() == ae]
            if narrowed:
                candidates = narrowed

        target = _as_date(committed_date)
        if target is not None:
            dated = [c for c in candidates
                     if (_as_date(c.committed_iso) is not None
                         and abs((_as_date(c.committed_iso) - target).days) <= max_days)]
            if dated:
                candidates = dated

        return dedupe(c.sha for c in candidates)
