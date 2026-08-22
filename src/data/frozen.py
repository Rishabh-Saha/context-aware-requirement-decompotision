"""Reading the frozen requirement set.

data/frozen/requirements.json is the locked Phase 1 deliverable, and everything downstream is keyed
to it: the 120 generations, the judge pass, the calibration sheet. Five places loaded it, and they
did not agree on how. Four filtered on `isinstance(r, dict) and r.get("issue_key")`, one on
`"_meta" not in r`, and one of the five was an inline dict comprehension rather than a function.

The two predicates agree on the real file and diverge on a malformed one: `"_meta" not in r` admits
a record carrying no issue_key, and raises TypeError rather than skipping if a record is not a dict
at all. The strict form is used here, since a record without an issue_key is not a requirement and
silently carrying one into a run would surface much later as a KeyError in an unrelated place.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_frozen_requirements(path: str | Path) -> list[dict]:
    """The frozen requirements, without the _meta provenance header the freeze script prepends.

    The header is dropped by requiring an issue_key rather than by position or by naming _meta, so a
    freeze file that later grows a second header entry does not start leaking one into the run.
    """
    records = json.loads(Path(path).read_text())
    return [r for r in records if isinstance(r, dict) and r.get("issue_key")]
