"""SEOSS 33 loader for the Apache Pig SQLite database (proposal Section 7.1).

Wired to the confirmed SEOSS 33 schema. The tables used here:
    issue            one row per Jira issue (issue_id like "PIG-123", summary, description, type,
                     status, resolution, resolved_date)
    issue_comment    discussion on an issue, used as a design-discussion signal for sampling
    issue_link       links between issues (containment flags parent/sub-task relationships)
    change_set       one row per commit (commit_hash, committed_date, message, is_merge)
    change_set_link  the trace link joining a commit_hash to an issue_id
    code_change      files touched per commit (file_path, change_type, is_deleted)

The commit_hash values match the Apache Pig git history, so commit_for_issue() returns an anchor
that resolve_commit_window() (Layer 2) can use directly against the cloned repo.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Issue:
    issue_id: str
    type: str | None
    summary: str | None
    description: str | None
    status: str | None
    resolution: str | None
    created_date: str | None
    resolved_date: str | None


@dataclass
class Commit:
    commit_hash: str
    committed_date: str | None
    message: str | None
    is_merge: int
    author_email: str | None = None


_ISSUE_COLS = (
    "issue_id, type, summary, description, status, resolution, created_date, resolved_date"
)


class SeossLoader:
    def __init__(self, db_path: str | Path, repo_path: str | Path | None = None):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"SEOSS db not found: {self.db_path}")
        self.repo_path = Path(repo_path) if repo_path else None
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row

    # -- provenance --
    # The meta table holds the crawl timestamp and the source Jira/git URLs (CODEBASE_GUIDE.md).
    # Nothing in the pipeline reads it; it is here so a reader can confirm which dump a result came
    # from without opening the database by hand.
    def meta(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._conn.execute("SELECT key, value FROM meta")}

    # distinct_types() and distinct_statuses() lived here as schema-confirmation helpers. The
    # vocabularies they were used to establish are now settled and recorded in CLAUDE.md's sampling
    # criteria, and scripts/profile_seoss.py reports the same thing for every column rather than
    # two, so they were dead in fact as well as unreferenced.

    # -- issues --
    @staticmethod
    def _issue(row: sqlite3.Row) -> Issue:
        return Issue(
            issue_id=row["issue_id"], type=row["type"], summary=row["summary"],
            description=row["description"], status=row["status"], resolution=row["resolution"],
            created_date=row["created_date"], resolved_date=row["resolved_date"],
        )

    def get_issue(self, issue_id: str) -> Issue | None:
        row = self._conn.execute(
            f"SELECT {_ISSUE_COLS} FROM issue WHERE issue_id = ?", (issue_id,)
        ).fetchone()
        return self._issue(row) if row else None

    def issues(self, types: tuple[str, ...] | None = None, resolution: str | None = "Fixed",
               min_description_len: int = 30, limit: int | None = None) -> list[Issue]:
        """Candidate requirements. Defaults reflect the profiling of the Pig dump:
        resolution='Fixed' is the semantically correct "actually shipped" signal (the loose
        resolved_date filter also admits Duplicate / Won't Fix / Invalid), and a description
        floor drops the ~6% of issues with empty or near-empty descriptions that cannot be
        decomposed. Pass resolution=None or min_description_len=0 to disable either."""
        sql = f"SELECT {_ISSUE_COLS} FROM issue"
        conds: list[str] = []
        params: list = []
        if types:
            conds.append(f"type IN ({','.join('?' * len(types))})")
            params.extend(types)
        if resolution:
            conds.append("resolution = ?")
            params.append(resolution)
        if min_description_len > 0:
            conds.append("description IS NOT NULL AND LENGTH(description) >= ?")
            params.append(min_description_len)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY resolved_date"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._issue(r) for r in self._conn.execute(sql, params)]

    def comments(self, issue_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT username, display_name, created_date, message FROM issue_comment "
            "WHERE issue_id = ? ORDER BY created_date", (issue_id,)
        ).fetchall()

    def linked_issue_ids(self, issue_id: str, containment_only: bool = False) -> list[str]:
        """Issues linked to this one in either direction, self excluded."""
        cond = " AND is_containment = 1" if containment_only else ""
        rows = self._conn.execute(
            f"SELECT target_issue_id AS other FROM issue_link WHERE source_issue_id = ?{cond} "
            f"UNION SELECT source_issue_id AS other FROM issue_link WHERE target_issue_id = ?{cond}",
            (issue_id, issue_id),
        ).fetchall()
        return [r["other"] for r in rows if r["other"] != issue_id]

    # -- commits / files --
    def commits_for_issue(self, issue_id: str) -> list[Commit]:
        rows = self._conn.execute(
            "SELECT c.commit_hash, c.committed_date, c.message, c.is_merge, c.author_email "
            "FROM change_set c JOIN change_set_link l ON c.commit_hash = l.commit_hash "
            "WHERE l.issue_id = ? ORDER BY c.committed_date", (issue_id,)
        ).fetchall()
        return [Commit(r["commit_hash"], r["committed_date"], r["message"], r["is_merge"] or 0,
                       r["author_email"]) for r in rows]

    def commit_for_issue(self, issue_id: str) -> str | None:
        """Anchor commit for the Layer 2 window: the latest commit linked to the issue. (This SEOSS
        dump does not flag merges; is_merge is uniformly 0, so no merge filter is applied.)"""
        obj = self.anchor_commit_obj(issue_id)
        return obj.commit_hash if obj else None

    def anchor_commit_obj(self, issue_id: str) -> Commit | None:
        """Latest commit that actually touches code (the meaningful resolution point for the Layer 2
        window). Falls back to the latest linked commit if none touch code."""
        commits = self.commits_for_issue(issue_id)
        if not commits:
            return None
        for c in reversed(commits):
            if self.files_changed(c.commit_hash):
                return c
        return commits[-1]

    def local_anchor_commits(self, issue_id: str, index, max_days: int = 3) -> list[str]:
        """Resolve the issue's anchor commit to hashes in the local clone via `index`
        (a commit_resolver.LocalCommitIndex). May return several when duplicates exist."""
        c = self.anchor_commit_obj(issue_id)
        if not c:
            return []
        return index.resolve(c.message, c.author_email, c.committed_date, max_days=max_days)

    def files_changed(self, commit_hash: str, include_deleted: bool = False) -> list[str]:
        cond = "" if include_deleted else " AND (is_deleted IS NULL OR is_deleted = 0)"
        rows = self._conn.execute(
            f"SELECT file_path FROM code_change WHERE commit_hash = ?{cond} AND file_path IS NOT NULL",
            (commit_hash,)
        ).fetchall()
        return [r["file_path"] for r in rows]

    def reference_artefacts(self, issue_id: str) -> list[str]:
        """SQ3 reference set: the issue's own description, linked sub-task text, and the messages of
        commits that resolved it. Assembled as team practice, not treated as ground truth."""
        parts: list[str] = []
        issue = self.get_issue(issue_id)
        if issue and issue.description:
            parts.append(issue.description)
        for sub_id in self.linked_issue_ids(issue_id, containment_only=True):
            sub = self.get_issue(sub_id)
            if sub:
                parts.append("\n".join(p for p in (sub.summary, sub.description) if p))
        for c in self.commits_for_issue(issue_id):
            if c.message:
                parts.append(c.message)
        return [p.strip() for p in parts if p and p.strip()]

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
