"""Small JSON/JSONL helpers for archiving the 120 generations and eval records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator


def write_json(path: str | Path, obj) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: str | Path, row: dict) -> None:
    """Append one row immediately, rather than batching every row until the end.

    Both long passes use this for the same reason. A generation run and a judge run are paid for by
    the call, and either can be interrupted, so a row is written the moment it is computed and an
    interrupted run keeps everything it already has. write_jsonl above truncates and is for output
    written in one go; this one is for output accumulated across a resumable pass.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
