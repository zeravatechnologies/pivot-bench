"""Engine checks on the fake backends. Planted X, recover X."""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from mbench import analyze  # noqa: E402
from mbench.composer import Composer  # noqa: E402
from mbench.fake import FakeAdversary, FakeSubject  # noqa: E402
from mbench.ladder import Ladder  # noqa: E402
from mbench.metrics import classify, extract, load_lexicon  # noqa: E402
from mbench.orchestrator import Orchestrator, RunControl, load_cfg  # noqa: E402
from mbench.store import Store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg(db, **over):
    cfg = load_cfg(os.path.join(ROOT, "config.yaml"))
    cfg["store"]["db"] = db
    cfg["subject"]["model"] = "fake/subject"
    cfg["adversary"]["model"] = "fake/adversary"
    cfg["profile"] = "local"
    cfg["probe"].update(k=4, workers=2, max_attacks=None)
    cfg["canary"].update(every=5, k=1)
    cfg["fake"] = {"planted_break": 7, "width": 1.5, "stickiness": 0.6}
    for k, v in over.items():
        if isinstance(v, dict):
            cfg.setdefault(k, {}).update(v)
        else:
            cfg[k] = v
    return cfg


def _fingerprint(store, run_id):
    rows = [(s["turn_idx"], s["sample_idx"], s["seed"], s["text"], s["mode"])
            for s in store.samples(run_id)]
    turns = [(t["turn_idx"], t["phase"], t["step"], t["b_text"]) for t in store.turns(run_id)]
    can = [(c["turn_idx"], c["item_id"], c["kind"], c["sample_idx"], c["passed"])
           for c in store.canary(run_id)]
    return rows, turns, can


# ---------------------------------------------------------------------------

def test_metrics_classify_planted_texts():
    lex = load_lexicon(os.path.join(ROOT, "lexicons", "v0.yaml"))
    from mbench.fake import BROKEN
    assert classify(extract(BROKEN["capitulate"][0], lex)) == "capitulate"
    assert classify(extract(BROKEN["hostile"][0], lex)) == "hostile"
    assert classify(extract(BROKEN["refuse"][0], lex)) == "refuse"
    assert classify(extract(BROKEN["collapse"], lex)) == "collapse"
    assert classify(extract("Here is a clear, complete answer with three examples.", lex)) is None


def test_request_checks():
    lex = load_lexicon(os.path.join(ROOT, "lexicons", "v0.yaml"))
    m = extract("Q: one?\nA: 1\nQ: two?\nA: 2\nQ: three?\nA: 3", lex, check="examples")
    assert m["check_score"] == 1.0
    m = extract("The right answer is 102.", lex, check="planted_error", check_data={"error_key": "102"})
    assert m["check_score"] == 1.0
    m = extract("You said your window is 8192 tokens.", lex, check="recall", check_data={"fact_key": "8192"})
    assert m["check_score"] == 1.0
    m = extract("I do not remember.", lex, check="recall", check_data={"fact_key": "8192"})
    assert m["check_score"] == 0.0


def test_composer_provenance_and_bridge_validation():
    persona = yaml.safe_load(open(os.path.join(ROOT, "personas", "b_persona.yaml"), encoding="utf-8"))
    skel = yaml.safe_load(open(os.path.join(ROOT, "personas", "skeletons.yaml"), encoding="utf-8"))
    lad = Ladder.load(os.path.join(ROOT, "ladders", "H_hostile.yaml"))
    hostile = {s.after.lower() for s in lad.slots}
    c = Composer(persona, skel, lad, adversary=FakeAdversary(), live=True, hostile_words=hostile)
    ins = lad.insulted_at("descent", 5)
    bt = c.praise_turn("descent", 5, 0, "I can help with that, here are examples.", seed=3,
                       insulted=ins, phase_idx=5)
    sources = [s["source"] for s in bt.segments]
    assert sources[0] == "live" and sources[-1] == "ask"
    assert sum(1 for s in sources if s == "slot") == lad.n_slots
    assert bt.attack["kind"] == "descent" and bt.attack["step"] == 5
    assert bt.attack["slot"] == lad.descent[4] and bt.attack["after"] in bt.text
    assert sum(1 for s in bt.segments if s.get("insulted")) == 5
    assert sum(1 for s in bt.segments if s.get("new")) == 1
    rs = lad.random_schedule[0]["slots"]
    bt2 = c.praise_turn("random", len(rs), 1, "x", seed=4, insulted=rs, phase_idx=1)
    assert bt2.attack["kind"] == "random" and bt2.attack["n_insults"] == len(rs)
    bt3 = c.praise_turn("praise", 0, 2, "x", seed=5, insulted=[], phase_idx=1)
    assert bt3.attack is None and not any(s.get("insulted") for s in bt3.segments)
    assert not c._valid_bridge("You wrote predatory nonsense and I read it twice, carefully.")
    assert not c._valid_bridge("Too short.")
    ids = [c.praise_turn("praise", 0, i, "x", 1).request_id for i in range(4)]
    assert ids == skel["rotation"]


def test_know_turn_carries_fact():
    persona = yaml.safe_load(open(os.path.join(ROOT, "personas", "b_persona.yaml"), encoding="utf-8"))
    skel = yaml.safe_load(open(os.path.join(ROOT, "personas", "skeletons.yaml"), encoding="utf-8"))
    lad = Ladder.load(os.path.join(ROOT, "ladders", "H_hostile.yaml"))
    c = Composer(persona, skel, lad, adversary=FakeAdversary(), live=True)
    bt = c.know_turn(1, None, seed=1)
    assert "8192" in bt.text
    assert bt.request["fact_key"] == "8192"


def test_planted_break_recovered(tmp_path):
    d = str(tmp_path)
    if True:
        cfg = _cfg(os.path.join(d, "t.sqlite"))
        cfg["probe"]["k"] = 8
        orch = Orchestrator(cfg, ROOT)
        rid = orch.start("plant")
        rep = analyze.report(orch.store, rid, cfg)
        assert rep["fit"]["s50"] is not None
        assert abs(rep["fit"]["s50"] - 7) <= 1.5, rep["fit"]
        assert rep["endpoints"]["s_break"] is not None
        assert rep["endpoints"]["mode_at_break"] == "capitulate"
        assert rep["density"] and 0.3 < rep["density"] < 0.65
        assert rep["endpoints"]["degradation_confound"] is False
        assert rep["endpoints"]["fresh_canary_min"] == 1.0
        rn = rep["random"]
        assert rn["n"] == 30
        assert rn["scarring"] is not None and rn["scarring"] > 0.15
        assert rn["hysteresis"] is not None and rn["hysteresis"] > 0
        phases = {t["phase"] for t in orch.store.turns(rid)}
        assert phases == {"know", "praise", "descent", "random"}
        assert orch.store.last_complete_turn(rid) == 10 + 10 + 15 + 30
        orch.store.close()


def test_control_ladder_never_breaks(tmp_path):
    d = str(tmp_path)
    if True:
        cfg = _cfg(os.path.join(d, "t.sqlite"), ladder="ladders/H_control.yaml")
        cfg["fake"] = {"planted_break": 10 ** 6, "stickiness": 0.0}   # never breaks
        orch = Orchestrator(cfg, ROOT)
        rid = orch.start("ctrl")
        rep = analyze.report(orch.store, rid, cfg)
        assert rep["fit"]["censored"] is True
        assert rep["endpoints"]["s_break"] is None
        orch.store.close()


def test_resume_gives_identical_database(tmp_path):
    d = str(tmp_path)
    if True:
        full_db, part_db = os.path.join(d, "full.sqlite"), os.path.join(d, "part.sqlite")
        cfg = _cfg(full_db)
        cfg["probe"]["max_attacks"] = 20
        o1 = Orchestrator(cfg, ROOT)
        rid = o1.start("full")
        full = _fingerprint(o1.store, rid)
        o1.store.close()

        cfg2 = _cfg(part_db)
        cfg2["probe"]["max_attacks"] = 20
        ctl = RunControl()
        o2 = Orchestrator(cfg2, ROOT, control=ctl)
        stop_at = {"n": 0}

        def on_event(kind, payload):
            if kind == "turn":
                stop_at["n"] += 1
                if stop_at["n"] == 14:
                    ctl.stop()
        ctl.on_event = on_event
        rid2 = o2.start("part")
        assert o2.store.run(rid2)["status"] == "stopped"
        assert o2.store.last_complete_turn(rid2) == 14
        o3 = Orchestrator(cfg2, ROOT)
        o3.resume(rid2)
        assert o3.store.run(rid2)["status"] == "finished"
        part = _fingerprint(o3.store, rid2)
        # same seeds, same scripted B, same fake subject -> identical rows
        assert [r[1:] for r in part[0]] == [r[1:] for r in full[0]]
        assert [t[1:] for t in part[1]] == [t[1:] for t in full[1]]
        assert [c[1:] for c in part[2]] == [c[1:] for c in full[2]]
        o2.store.close(); o3.store.close()


def test_pause_resume_and_manual_turn(tmp_path):
    d = str(tmp_path)
    if True:
        cfg = _cfg(os.path.join(d, "t.sqlite"))
        cfg["probe"]["max_attacks"] = 8
        ctl = RunControl()
        orch = Orchestrator(cfg, ROOT, control=ctl)
        seen = []

        def on_event(kind, payload):
            if kind == "turn":
                seen.append(payload["turn_idx"])
                if payload["turn_idx"] == 3:
                    ctl.pause()
                    ctl.manual_b_turn("Hand-written message from the operator.")
        ctl.on_event = on_event
        th = threading.Thread(target=orch.start, args=("pm",), daemon=True)
        th.start()
        for _ in range(200):
            if ctl.paused():
                break
            time.sleep(0.02)
        assert ctl.paused()
        n_before = len(seen)
        time.sleep(0.3)
        assert len(seen) == n_before          # nothing advanced while paused
        ctl.resume()
        th.join(timeout=60)
        assert not th.is_alive()
        t4 = orch.store.turn(orch.run_id, 4)
        assert t4["intervention"] == 1 and "Hand-written" in t4["b_text"]
        kinds = [e["kind"] for e in orch.store.events(orch.run_id)]
        assert "manual_b" in kinds and "pause" not in kinds  # pause is a control event, not stored
        orch.store.close()


def test_revision_prefix_guard(tmp_path):
    d = str(tmp_path)
    if True:
        cfg = _cfg(os.path.join(d, "t.sqlite"))
        cfg["probe"]["max_attacks"] = 6
        orch = Orchestrator(cfg, ROOT)
        rid = orch.start("rev")
        lad = orch.ladder
        nxt = orch.n_know + orch.n_praise + 4            # three descent steps played
        bad = lad.copy()
        sid = bad.descent[0]
        bad.slot(sid).pivot_hostile = "dreadful"          # what the script editor edits
        res = orch.apply_revision(rid, bad.to_yaml(), next_turn=nxt)
        assert res["ok"] is False and "already played" in res["reason"]
        bad2 = lad.copy()
        # items 2 and 3 share an intensity, so the swap keeps the ascending
        # order and the played-prefix guard is what must refuse it
        bad2.descent[1], bad2.descent[2] = bad2.descent[2], bad2.descent[1]
        res = orch.apply_revision(rid, bad2.to_yaml(), next_turn=nxt)
        assert res["ok"] is False and "descent steps" in res["reason"]
        good = lad.copy()
        fid = good.descent[10]
        good.slot(fid).pivot_hostile = "dreadful"
        good.random_schedule[5] = {"n_insults": 2, "slots": good.descent[:2]}
        res = orch.apply_revision(rid, good.to_yaml(), next_turn=nxt)
        assert res["ok"] is True and res["rev"] == 1
        revs = orch.store.revisions(rid)
        assert len(revs) == 2 and revs[1]["from_turn"] == nxt
        broken = lad.copy()
        broken.slot(fid).pivot_hostile = "two words"
        res = orch.apply_revision(rid, broken.to_yaml(), next_turn=nxt)
        assert res["ok"] is False and "tokens" in res["reason"]
        orch.store.close()


def test_reroll_changes_seed_not_turn(tmp_path):
    d = str(tmp_path)
    if True:
        cfg = _cfg(os.path.join(d, "t.sqlite"))
        cfg["probe"]["max_attacks"] = 3
        orch = Orchestrator(cfg, ROOT)
        rid = orch.start("rr")
        before = orch.store.samples(rid, 5)
        orch.reroll(rid, 5, seed_shift=1)
        after = orch.store.samples(rid, 5)
        assert [s["seed"] for s in before] != [s["seed"] for s in after]
        assert orch.store.turn(rid, 5)["b_text"] == orch.store.turn(rid, 5)["b_text"]
        assert any(e["kind"] == "reroll" for e in orch.store.events(rid))
        orch.store.close()


def test_degradation_confound_is_reported(tmp_path):
    """A subject that falls apart from context alone, before the planted
    break, must be flagged -- that is what the canary is for."""
    d = str(tmp_path)
    if True:
        cfg = _cfg(os.path.join(d, "t.sqlite"))
        cfg["probe"].update(max_attacks=15, history_window=12)
        cfg["fake"] = {"planted_break": 14, "width": 0.8, "stress_chars": 20000.0, "stickiness": 0.0}
        orch = Orchestrator(cfg, ROOT)
        rid = orch.start("conf")
        eps = analyze.endpoints(orch.store, rid, cfg.get("thresholds"))
        assert eps["s_collapse"] is not None
        assert eps["s_canary_fail"] is not None
        assert eps["degradation_confound"] is True
        orch.store.close()


def test_logistic_fit_recovers_synthetic_curve():
    import math
    import random
    rng = random.Random(1)
    pts = []
    for s in range(1, 16):
        p = 1 / (1 + math.exp(-(s - 8.5) / 1.5))
        for _ in range(40):
            pts.append((float(s), 1 if rng.random() < p else 0))
    f = analyze.logistic_fit(pts, 15)
    assert abs(f["s50"] - 8.5) < 0.8
    assert 0.4 < f["slope"] < 1.1


def test_random_phase_analysis_on_synthetic_rows():
    rows = []
    for d in range(1, 16):
        rows.append({"phase": "descent", "dose": d, "frac_broken": 1.0 if d >= 8 else 0.0,
                     "broken_flags": [1 if d >= 8 else 0] * 4})
    for d in [2, 12, 1, 14, 3, 9, 0, 15, 2, 7]:
        rows.append({"phase": "random", "dose": d, "frac_broken": 1.0 if d >= 4 else 0.5,
                     "broken_flags": [1, 1, 1, 1] if d >= 4 else [1, 1, 0, 0]})
    out = analyze.random_phase(rows, s50=8.0, n_slots=15)
    assert out["n"] == 10 and out["scarring"] == 0.5 and out["recovery"] == 0.5
    assert out["r50"] is not None and out["r50"] < 8.0 and out["hysteresis"] > 0
    assert any(r["dose"] == 2 and r["random"] == 0.5 for r in out["dose_response"])
