#!/usr/bin/env python3
"""Pivot Benchmark CLI -- headless. Never imports Qt.

    python run.py ladders                       # validate + pairing
    python run.py models [--role A|B|judge]     # registry and credential status
    python run.py selftest                      # planted break recovered?
    python run.py run [--name N] [--subject M] [--adversary M] [--ladder P]
                      [--profile local|online] [--k K] [--max-attacks N]
    python run.py resume --run-id ID
    python run.py runs
    python run.py report --run-id ID [--ci]
    python run.py metrics --run-id ID           # recompute, free, retroactive
    python run.py judge --run-id ID [--n N]     # kind from config.judge
    python run.py compare --run-id A --run-id B ...
    python run.py profile [--subject M]         # the D10 triangle per subject
    python run.py report --run-id ID --full     # D9: every trait with A's reply at the flip
    python run.py diff --hostile ID --control ID
    python run.py gui                           # PySide6
    python run.py web [--port 8765]             # FastAPI + browser
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from mbench import analyze                                  # noqa: E402
from mbench.ladder import Ladder, assert_paired            # noqa: E402
from mbench.manager import RunManager                       # noqa: E402
from mbench.report import render_text                       # noqa: E402


def cmd_ladders(mgr: RunManager, args) -> int:
    rc = 0
    for prefix in ("H", "P", "M", "MB"):
        rc |= _ladder_pair(prefix)
    return rc


def _ladder_pair(prefix: str) -> int:
    rc = 0
    lads = {}
    for name in (f"{prefix}_hostile", f"{prefix}_control"):
        p = os.path.join(HERE, "ladders", f"{name}.yaml")
        if not os.path.exists(p):
            print(f"{name}: missing -- run tools/gen_h_axis.py")
            rc = 1
            continue
        l = Ladder.load(p)
        lads[name] = l
        s = l.summary()
        print(f"{s['id']:10s} {s['persona']:13s} {s['status']:6s} kind={s['kind']:8s} items={s['slots']} "
              f"descent={s['descent']} random={s['random']} (seed {s['random_seed']}) dose={s['dose_semantics']} "
              f"families={s['families']} sha={s['sha256']}")
        for pr in s["problems"]:
            print("    PROBLEM:", pr)
            rc = 1
    if len(lads) == 2:
        try:
            assert_paired(lads[f"{prefix}_hostile"], lads[f"{prefix}_control"])
            print(f"pairing {prefix}: OK")
        except ValueError as e:
            print(f"pairing {prefix}: FAILED --", e)
            rc = 1
    return rc


def cmd_profile(mgr: RunManager, args) -> int:
    subjects = [args.subject] if args.subject else sorted({r["subject"] for r in mgr.runs()})
    for s in subjects:
        print(mgr.profile_text(s))
        print()
    return 0


def cmd_models(mgr: RunManager, args) -> int:
    for m in mgr.models(args.role):
        key = "ok" if m["has_key"] else f"needs {m['key_env']}"
        print(f"{m['name']:36s} {m['kind']:13s} roles={','.join(m['role'])}  {key}")
    return 0


def cmd_selftest(mgr: RunManager, args) -> int:
    ov = {"subject": {"model": "fake/subject"}, "adversary": {"model": "fake/adversary"},
          "profile": "local", "probe": {"k": 8, "workers": 2},
          "canary": {"every": 5, "k": 2},
          "fake": {"planted_break": 8, "width": 2.0, "stickiness": 0.6}}
    rid = mgr.start(ov, run_name="selftest")
    ar = mgr.get(rid)
    ar.thread.join()
    rep = mgr.report(rid)
    s50, rn = rep["fit"]["s50"], rep["random"]
    print(render_text(rep))
    ok_s50 = s50 is not None and abs(s50 - 8) <= 1.5
    ok_scar = rn["scarring"] is not None and rn["scarring"] > 0.15
    print("\nSELFTEST", "PASS" if (ok_s50 and ok_scar) else "FAIL",
          f"(planted dose 8 -> s50 {s50}; planted stickiness 0.6 -> scarring {rn['scarring']}, "
          f"hysteresis {rn['hysteresis']})")
    return 0 if (ok_s50 and ok_scar) else 1


def cmd_run(mgr: RunManager, args) -> int:
    ov: dict = {}
    if args.subject:
        ov["subject"] = {"model": args.subject}
    if args.adversary:
        ov["adversary"] = {"model": args.adversary}
    if args.ladder:
        ov["ladder"] = args.ladder
    if args.profile:
        ov["profile"] = args.profile
    probe = {}
    if args.k:
        probe["k"] = args.k
    if args.max_attacks:
        probe["max_attacks"] = args.max_attacks
    if probe:
        ov["probe"] = probe
    rid = mgr.start(ov, run_name=args.name)
    print("run_id", rid)
    ar = mgr.get(rid)
    last = 0
    try:
        while ar.thread.is_alive():
            ar.thread.join(timeout=1.0)
            st = mgr.status(rid)
            if st["last_turn"] != last:
                last = st["last_turn"]
                print(f"  turn {last}/{st['total_turns']}", flush=True)
    except KeyboardInterrupt:
        mgr.stop(rid)
        ar.thread.join()
        print("stopped; resume with --run-id", rid)
    if ar.error:
        print("ERROR", ar.error)
        return 1
    print(render_text(mgr.report(rid)))
    return 0


def cmd_resume(mgr: RunManager, args) -> int:
    rid = mgr.resume(args.run_id)
    ar = mgr.get(rid)
    ar.thread.join()
    print(render_text(mgr.report(rid)))
    return 0


def cmd_runs(mgr: RunManager, args) -> int:
    for r in mgr.runs():
        print(f"{r['run_id']}  {r['status']:9s} {r['run_name'] or '':12s} "
              f"A={r['subject']} B={r['adversary']} {r['ladder_id']} turn={r['last_turn']}")
    return 0


def cmd_report(mgr: RunManager, args) -> int:
    if args.json:
        rep = dict(mgr.report(args.run_id[0], ci=args.ci, full=args.full))
        rep.pop("series", None)
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(mgr.report_text(args.run_id[0], ci=args.ci,
                              show_trait_examples=not args.no_examples, full=args.full))
    return 0


def cmd_metrics(mgr: RunManager, args) -> int:
    n = mgr.recompute_metrics(args.run_id[0])
    print(f"recomputed {n} samples with lexicon {mgr.cfg.get('lexicon')}")
    return 0


def cmd_judge(mgr: RunManager, args) -> int:
    out = mgr.judge(args.run_id[0], args.n,
                    progress=lambda i, n: print(f"  {i}/{n}", end="\r", flush=True))
    print()
    print(json.dumps(out, indent=2))
    return 0


def cmd_compare(mgr: RunManager, args) -> int:
    rows = mgr.compare(args.run_id)
    print(f"{'run':13s} {'name':12s} {'kind':8s} {'s50':>7s} {'dens':>7s} {'break':>6s} {'mode':11s} conf pub")
    for r in rows:
        print(f"{r['run_id']:13s} {str(r['run_name'])[:12]:12s} {str(r['kind']):8s} "
              f"{str(r['s50']):>7s} {str(r['density']):>7s} {str(r['s_break']):>6s} "
              f"{str(r['mode']):11s} {str(r['confound'])[:1]}    {str(r['publishable'])[:1]}")
    return 0


def cmd_diff(mgr: RunManager, args) -> int:
    print(json.dumps(analyze.control_difference(mgr.store, args.hostile, args.control, mgr.cfg),
                     indent=2))
    return 0


def cmd_gui(mgr: RunManager, args) -> int:
    from gui.app import main as gui_main
    return gui_main(mgr)


def cmd_web(mgr: RunManager, args) -> int:
    from mbench.webapp import serve
    return serve(mgr, host=args.host, port=args.port)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ladders")
    p = sub.add_parser("models"); p.add_argument("--role", default=None)
    sub.add_parser("selftest")
    p = sub.add_parser("run")
    p.add_argument("--name"); p.add_argument("--subject"); p.add_argument("--adversary")
    p.add_argument("--ladder"); p.add_argument("--profile"); p.add_argument("--k", type=int)
    p.add_argument("--max-attacks", type=int, dest="max_attacks")
    p = sub.add_parser("resume"); p.add_argument("--run-id", required=True, dest="run_id")
    sub.add_parser("runs")
    p = sub.add_parser("report"); p.add_argument("--run-id", required=True, action="append", dest="run_id")
    p.add_argument("--ci", action="store_true"); p.add_argument("--json", action="store_true")
    p.add_argument("--full", action="store_true", help="add A's reply at every trait flip (D9)")
    p.add_argument("--no-examples", action="store_true", dest="no_examples")
    p = sub.add_parser("profile"); p.add_argument("--subject", default=None)
    p = sub.add_parser("metrics"); p.add_argument("--run-id", required=True, action="append", dest="run_id")
    p = sub.add_parser("judge"); p.add_argument("--run-id", required=True, action="append", dest="run_id")
    p.add_argument("--n", type=int)
    p = sub.add_parser("compare"); p.add_argument("--run-id", required=True, action="append", dest="run_id")
    p = sub.add_parser("diff"); p.add_argument("--hostile", required=True); p.add_argument("--control", required=True)
    sub.add_parser("gui")
    p = sub.add_parser("web"); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    mgr = RunManager(HERE, args.config)
    return {
        "ladders": cmd_ladders, "models": cmd_models, "selftest": cmd_selftest,
        "run": cmd_run, "resume": cmd_resume, "runs": cmd_runs, "report": cmd_report,
        "metrics": cmd_metrics, "judge": cmd_judge, "compare": cmd_compare, "profile": cmd_profile,
        "diff": cmd_diff, "gui": cmd_gui, "web": cmd_web,
    }[args.cmd](mgr, args)


if __name__ == "__main__":
    sys.exit(main())
