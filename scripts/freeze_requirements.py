"""Freeze the sampled requirement set to data/frozen/requirements.json.

This is the Phase 1 deliverable step. Sampling is deterministic given the database and the current
filters, so re-running should reproduce the same set. Because everything downstream (the 120
generations, the evaluation, any annotation) is keyed to this file, it is treated as write-once:
the script refuses to overwrite an existing frozen file unless --force is passed, so the set can
never be clobbered by accident.

Usage:
    python scripts/freeze_requirements.py                 # first freeze, or no-op if file exists
    python scripts/freeze_requirements.py --check         # re-sample to a temp file and diff, no write
    python scripts/freeze_requirements.py --force          # deliberately regenerate (overwrites)
    python scripts/freeze_requirements.py --target-n 30    # different sample size

Run from the repo root with the venv active.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Make the repo root importable when run as `python scripts/freeze_requirements.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.commit_resolver import LocalCommitIndex  # noqa: E402
from src.data.sampling import TARGET_N, sample_requirements  # noqa: E402
from src.data.seoss_loader import SeossLoader  # noqa: E402
from src.utils.io import write_json  # noqa: E402

from src.paths import DEFAULT_DB, DEFAULT_REPO  # noqa: E402
from src.paths import DEFAULT_FROZEN as DEFAULT_OUT  # noqa: E402  (this script writes it)


def build(db: str, repo: str, target_n: int) -> list[dict]:
    idx = LocalCommitIndex(repo)
    with SeossLoader(db, repo) as loader:
        sampled = sample_requirements(loader, target_n=target_n, commit_index=idx)
    records = [asdict(r) for r in sampled]
    # Provenance header so a frozen file is self-describing and auditable.
    meta = {
        "_meta": {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "db": db,
            "repo": repo,
            "target_n": target_n,
            "n_frozen": len(records),
            "n_resolved_to_local": sum(1 for r in records if r.get("local_commits")),
        }
    }
    return [meta, *records]


def main() -> int:
    p = argparse.ArgumentParser(description="Freeze the sampled requirement set.")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--target-n", type=int, default=TARGET_N)
    p.add_argument("--force", action="store_true", help="overwrite an existing frozen file")
    p.add_argument("--check", action="store_true",
                   help="re-sample and compare to the existing file without writing")
    args = p.parse_args()

    out = Path(args.out)

    if args.check:
        if not out.exists():
            print(f"No existing file at {out} to check against.")
            return 1
        fresh = build(args.db, args.repo, args.target_n)
        existing = json.loads(out.read_text())
        # Compare the requirement records only, ignoring the _meta/timestamp header.
        fresh_body = [r for r in fresh if "_meta" not in r]
        existing_body = [r for r in existing if "_meta" not in r]
        if fresh_body == existing_body:
            print(f"IDENTICAL: re-sampling reproduces {len(fresh_body)} requirements. Safe.")
            return 0
        print("DIFFERENT: re-sampling does NOT match the frozen file. Investigate before --force.")
        fresh_keys = {r["issue_key"] for r in fresh_body}
        old_keys = {r["issue_key"] for r in existing_body}
        print("  only in fresh:", sorted(fresh_keys - old_keys))
        print("  only in frozen:", sorted(old_keys - fresh_keys))
        return 2

    if out.exists() and not args.force:
        print(f"{out} already exists. This is the locked Phase 1 deliverable.")
        print("Use --check to verify it still reproduces, or --force to deliberately regenerate.")
        return 1

    records = build(args.db, args.repo, args.target_n)
    write_json(out, records)
    body = [r for r in records if "_meta" not in r]
    resolved = sum(1 for r in body if r.get("local_commits"))
    print(f"Froze {len(body)} requirements to {out} ({resolved}/{len(body)} resolved to local commits).")
    print("Remember to track it: git add -f", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
