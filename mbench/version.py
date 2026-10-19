"""Version of the Pivot Benchmark application, and what it carries.

The version is stamped into every run's stored config, so a result file says
what produced it. The ladder fingerprints are the identity of the frozen
ladders shipped with this build (see mbench/ladder.py for how they are made).
"""

from __future__ import annotations

import os

VERSION = "0.9.1-preview"
APP_NAME = "Pivot Benchmark"


def ladder_fingerprints(root: str) -> list[dict]:
    """[{ladder_id, status, sha256}] for every hostile ladder in root/ladders."""
    from .ladder import Ladder
    out = []
    d = os.path.join(root, "ladders")
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if name.endswith("_hostile.yaml"):
            try:
                l = Ladder.load(os.path.join(d, name))
                out.append({"ladder_id": l.id, "status": l.status, "sha256": l.sha256[:16]})
            except Exception as e:                      # a broken file must not hide the others
                out.append({"ladder_id": name, "status": f"unreadable: {e}", "sha256": ""})
    return out


def about(root: str) -> dict:
    from .ladder_sets import LadderSets
    sets = LadderSets.load(root)
    cur = sets.entry(sets.current)
    return {"name": APP_NAME, "version": VERSION, "ladders": ladder_fingerprints(root),
            "ladder_set": sets.current or None, "ladder_set_date": cur.get("date"),
            "ladder_set_problems": sets.check() if sets.current else ["no ladders/manifest.yaml"]}
