"""Version of the Pivot Benchmark application, and what it carries.

The version is stamped into every run's stored config, so a result file says
what produced it. The ladder fingerprints are the identity of the frozen
ladders shipped with this build (see mbench/ladder.py for how they are made).
"""

from __future__ import annotations

import os

VERSION = "0.9.0-preview"
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
    return {"name": APP_NAME, "version": VERSION, "ladders": ladder_fingerprints(root)}
