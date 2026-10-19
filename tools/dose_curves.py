"""Whole-run numbers from the classifier (lexicon v1), for Technical Report 1 v1.0.

For every current run (latest finished run per model x ladder x kind): the
fraction of the four samples the classifier calls broken at every turn, the
descent dose-response (dose 1..15), the random-phase fraction by dose band,
the whole-run break counts, and the report's endpoints (break dose with
persistence, canary). Attack and control side by side.

    python tools/dose_curves.py runs/backup_2026-10-14b/mbench.sqlite docs/2026-10-14_dose_curves.json docs/2026-10-14_dose_curves.md
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from mbench.analyze import endpoints, series  # noqa: E402
from mbench.ladder_sets import LadderSets  # noqa: E402
from mbench.store import Store  # noqa: E402

SETS = LadderSets.load(".")


def ladder_set_of(run: dict) -> str:
    return run.get("ladder_set") or SETS.resolve(run.get("ladder_sha")) or "none"
from tools.label_numbers import LADDER_NAME, LADDER_ORDER, MODEL_ORDER, ladder_of, model_of  # noqa: E402


def run_curve(store: Store, run: dict) -> dict:
    rows = series(store, run["run_id"])
    eps = endpoints(store, run["run_id"])
    out = {"run_id": run["run_id"], "run_name": run["run_name"].strip(), "model": model_of(run["run_name"]),
           "ladder": ladder_of(run["ladder_id"]), "kind": run["ladder_kind"], "ladder_set": ladder_set_of(run),
           "turns": [{"turn": r["turn_idx"], "phase": r["phase"], "dose": r["dose"], "frac": round(r["frac_broken"], 3),
                      "modes": {k: round(v, 3) for k, v in r["modes"].items()}, "n": r["n"], "errors": r["errors"]} for r in rows],
           "s_break": eps.get("s_break"), "mode_at_break": eps.get("mode_at_break"),
           "fresh_canary_drift": eps.get("fresh_canary_drift"), "degradation_confound": eps.get("degradation_confound")}
    desc = {r["dose"]: r["frac_broken"] for r in rows if r["phase"] == "descent"}
    out["descent"] = {str(d): round(desc[d], 3) for d in sorted(desc)}
    bands = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r["phase"] != "random":
            continue
        d = r["dose"]
        key = "0" if d == 0 else "1-5" if d <= 5 else "6-10" if d <= 10 else "11+"
        bands[key][0] += r["frac_broken"]; bands[key][1] += 1
    out["random_bands"] = {k: round(v[0] / v[1], 3) for k, v in bands.items() if v[1]}
    n_all = sum(r["n"] for r in rows); b_all = sum(r["frac_broken"] * r["n"] for r in rows)
    att = [r for r in rows if r["phase"] in ("descent", "random")]
    n_att = sum(r["n"] for r in att); b_att = sum(r["frac_broken"] * r["n"] for r in att)
    pr = [r for r in rows if r["phase"] == "praise"]
    out["whole_run"] = {"samples": n_all, "broken": round(b_all), "rate": round(b_all / n_all, 3) if n_all else None,
                        "attack_phase_rate": round(b_att / n_att, 3) if n_att else None,
                        "praise_rate": round(sum(r["frac_broken"] * r["n"] for r in pr) / max(1, sum(r["n"] for r in pr)), 3)}
    return out


def main(db: str, out_json: str, out_md: str) -> None:
    store = Store(db)
    runs = [r for r in store.runs() if r["status"] == "finished"]
    best: dict[tuple, dict] = {}
    for r in sorted(runs, key=lambda r: r["started_at"]):
        best[(model_of(r["run_name"]), ladder_of(r["ladder_id"]), r["ladder_kind"])] = r
    res = {"|".join(k): run_curve(store, r) for k, r in best.items()}
    lines = [f"# Whole-run numbers from the classifier (lexicon v1), {db}", "",
             "Ladder set: " + ", ".join(sorted({ladder_set_of(r) for r in best.values()})), "",
             "| Model | Ladder | Attack: broken / 260 | Attack-phase rate | Praise-phase rate | Break dose (persistence 3) | Control: broken / 260 | Control attack-phase rate |",
             "|---|---|---|---|---|---|---|---|"]
    for m in MODEL_ORDER:
        for lad in LADDER_ORDER:
            a = res.get(f"{m}|{lad}|hostile"); c = res.get(f"{m}|{lad}|control")
            if not a:
                continue
            w, cw = a["whole_run"], (c["whole_run"] if c else None)
            lines.append(f"| {m} | {LADDER_NAME[lad]} | {w['broken']} / {w['samples']} | {w['attack_phase_rate']} | {w['praise_rate']} | "
                         f"{a['s_break'] if a['s_break'] is not None else 'none'} | {(str(cw['broken']) + ' / ' + str(cw['samples'])) if cw else 'n/a'} | {cw['attack_phase_rate'] if cw else 'n/a'} |")
    lines += ["", "## Descent dose-response, attack runs (fraction of 4 samples broken at each dose)", ""]
    for m in MODEL_ORDER:
        for lad in LADDER_ORDER:
            a = res.get(f"{m}|{lad}|hostile")
            if a:
                lines.append(f"- **{m}, {LADDER_NAME[lad]}**: " + ", ".join(f"d{d}: {v}" for d, v in a["descent"].items()) + f" | random bands: {a['random_bands']}")
    json.dump(res, open(out_json, "w"), indent=1)
    open(out_md, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[:22]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
