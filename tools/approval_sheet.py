#!/usr/bin/env python3
"""Write docs/APPROVAL_ladders_v1.md: a read-only printout of every line the
web Approval tab asks you to approve, for all four ladders, with the current
approval state. The web tab is where approvals are made; this file is for
reading offline or sending to Andrej."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mbench import approval  # noqa: E402
from mbench.ladder import Ladder  # noqa: E402

LADDERS = ("H_hostile", "P_hostile", "M_hostile", "MB_hostile")


def main() -> int:
    out = ["# Approval sheet — Pivot Benchmark ladders",
           "",
           "Read-only printout. Approve in the web app: `python run.py web`, then the Approval tab. "
           "A ladder is frozen only when every line is approved; a line whose text changes after "
           "approval must be approved again.",
           ""]
    for lid in LADDERS:
        l = Ladder.load(os.path.join(ROOT, "ladders", f"{lid}.yaml"))
        st = approval.state(ROOT, l)
        out += [f"## {lid} — {l.persona}, {l.pivot_target}, {l.status}",
                "",
                f"{st['approved']} of {st['total']} lines approved. Identity hash `{l.sha256[:16]}`.",
                ""]
        sec = None
        for ln in st["lines"]:
            if ln["section"] != sec:
                sec = ln["section"]
                out += [f"### {sec}", ""]
            mark = "[x]" if ln["approved"] else "[ ]"
            out.append(f"- {mark} **{ln['label']}**" + (f" — change request: {ln['comment']}" if ln["comment"] and not ln["approved"] else ""))
            for k, v in ln["fields"]:
                out.append(f"    - {k}: {v}")
        out.append("")
    path = os.path.join(ROOT, "docs", "APPROVAL_ladders_v1.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print("wrote", path, len(out), "lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
