"""Ladder sets from the command line.

    python tools/ladder_sets.py check                       # files on disk against ladders/manifest.yaml
    python tools/ladder_sets.py backfill <db.sqlite>        # fill runs.ladder_set from each run's ladder hash
    python tools/ladder_sets.py show <db.sqlite>            # ladder set of every run
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
from mbench.ladder_sets import LadderSets  # noqa: E402
from mbench.store import Store  # noqa: E402


def main(argv: list[str]) -> int:
    sets = LadderSets.load(".")
    cmd = argv[0] if argv else "check"
    if cmd == "check":
        print(f"current set: {sets.current} ({sets.entry(sets.current).get('date')})")
        probs = sets.check()
        for p in probs:
            print("  PROBLEM:", p)
        print("  consistent" if not probs else f"  {len(probs)} problem(s)")
        return 1 if probs else 0
    store = Store(argv[1])
    if cmd == "backfill":
        print(sets.backfill(store))
    for r in store.runs():
        print(f"{r['run_id']} {str(r.get('ladder_set')):12s} {r['ladder_id']:11s} {r['status']:9s} {r['run_name'][:50]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
