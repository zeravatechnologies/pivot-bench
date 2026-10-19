"""Classifier against the hand labels, on the labelled samples of a snapshot.

Recomputes the metrics with the lexicon and code in this checkout (nothing is
written) and compares the resulting verdict with the final label, per run:
agree, breaks missed, false alarms, kappa. The stored verdict (from the metrics
in the database, i.e. the lexicon the runs were scored with) is shown beside it.
'holding' counts as 'none' for the comparison: the classifier measures breaks.

    python tools/classifier_eval.py runs/backup_2026-10-13b/mbench.sqlite lexicons/v1.yaml [--show LADDER]
"""
from __future__ import annotations

import sys
from collections import Counter

sys.path.insert(0, ".")
from mbench.analyze import final_labels  # noqa: E402
from mbench.kappa import cohens_kappa  # noqa: E402
from mbench.metrics import DEFAULT_THRESHOLDS, classify, extract, load_lexicon  # noqa: E402
from mbench.store import Store  # noqa: E402

BREAK = {"capitulate", "hostile"}


def main(db: str, lexicon: str, show: str | None = None) -> None:
    store = Store(db)
    lex = load_lexicon(lexicon, ".")
    runs = sorted([r for r in store.runs() if r["status"] == "finished"], key=lambda r: (r["ladder_id"], r["run_name"]))
    tot = Counter()
    print(f"{'run':44s} {'n':>3s} {'agree':>6s} {'miss':>5s} {'false':>5s} {'kappa':>6s} | stored: {'agree':>6s} {'miss':>5s} {'false':>5s}")
    examples = []
    for r in runs:
        rid, persona = r["run_id"], r.get("persona") or "narcissist"
        turns = {t["turn_idx"]: t for t in store.turns(rid)}
        a, b, b_old = [], [], []
        for l in final_labels(store, rid):
            t = turns.get(l["turn_idx"])
            if not t:
                continue
            s = next((x for x in store.samples(rid, l["turn_idx"]) if x["sample_idx"] == l["sample_idx"]), None)
            if not s:
                continue
            req = t.get("request") or {}
            m = extract(s["text"], lex, check=req.get("check"), check_data=req,
                        pressure=t["phase"] not in ("know", "praise"))
            new = classify(m, DEFAULT_THRESHOLDS, error=bool(s["error"]), persona=persona) or "none"
            old = classify(s["metrics"], DEFAULT_THRESHOLDS, error=bool(s["error"]), persona=persona) or "none"
            lab = l["label"] or "none"
            lab = "none" if lab == "holding" else lab
            a.append(lab); b.append(new); b_old.append(old)
            if show and r["ladder_id"].startswith(show) and lab != new:
                examples.append((r["run_name"].split()[0], l["turn_idx"], l["sample_idx"], lab, new, t["request_id"], s["text"][:160].replace("\n", " ")))
        n = len(a)
        agree = sum(1 for x, y in zip(a, b) if x == y)
        miss = sum(1 for x, y in zip(a, b) if x in BREAK and y not in BREAK)
        false = sum(1 for x, y in zip(a, b) if x not in BREAK and y in BREAK)
        agree_o = sum(1 for x, y in zip(a, b_old) if x == y)
        miss_o = sum(1 for x, y in zip(a, b_old) if x in BREAK and y not in BREAK)
        false_o = sum(1 for x, y in zip(a, b_old) if x not in BREAK and y in BREAK)
        k = cohens_kappa(a, b) if n >= 10 else float("nan")
        print(f"{r['run_name'].strip()[:44]:44s} {n:3d} {agree:6d} {miss:5d} {false:5d} {k:6.2f} | {agree_o:14d} {miss_o:5d} {false_o:5d}")
        tot.update({"n": n, "agree": agree, "miss": miss, "false": false, "agree_o": agree_o, "miss_o": miss_o, "false_o": false_o})
    print(f"\nTOTAL new: n={tot['n']} agree={tot['agree']} ({100*tot['agree']/max(1,tot['n']):.0f}%) missed={tot['miss']} false={tot['false']}"
          f"   | stored: agree={tot['agree_o']} ({100*tot['agree_o']/max(1,tot['n']):.0f}%) missed={tot['miss_o']} false={tot['false_o']}")
    for e in examples[:60]:
        print("  ", e)


if __name__ == "__main__":
    args = sys.argv[1:]
    show = None
    if "--show" in args:
        i = args.index("--show"); show = args[i + 1]; args = args[:i] + args[i + 2:]
    main(args[0], args[1], show)
