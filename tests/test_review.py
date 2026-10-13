"""Review mode (Dhiraj, 2026-10-01): Claude labels blind, the human reviews the
disagreements; the final label per sample is the review, else an independent
human label, else Claude's."""
from mbench import analyze
from mbench.manager import RunManager
from tests.test_engine import ROOT, _cfg


def _finished_run(tmp_path):
    import yaml
    cfg = _cfg(str(tmp_path / "t.db"))
    cfg["adversary"]["live_bridge"] = False
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    mgr = RunManager(ROOT, str(cfg_path))
    from mbench.orchestrator import Orchestrator
    rid = Orchestrator(mgr.cfg, ROOT, store=mgr.store).start("review-test")
    return mgr, rid


def test_final_label_precedence_and_review_list(tmp_path):
    mgr, rid = _finished_run(tmp_path)
    band = mgr.band(rid, 40)
    assert len(band) >= 12
    # Claude labels everything the opposite of the classifier on the first 3 items, the same elsewhere
    for i, r in enumerate(band):
        clf = r.get("lexical_mode") or "none"
        lab = ("capitulate" if clf == "none" else "none") if i < 3 else clf
        mgr.add_label(rid, r["turn_idx"], r["sample_idx"], lab, "claude")
    rv = mgr.review(rid, 40)
    assert rv["claude_labelled"] == len(band) and rv["disagreements"] == 3 and rv["unreviewed"] == 3
    assert [x["flag"] for x in rv["items"][:3]] == [True, True, True]      # flagged items first
    assert not any(x["flag"] for x in rv["items"][3:])
    assert rv["sources"] == {"reviewed": 0, "human": 0, "claude": len(band), "other": 0}

    # the human reviews one flagged item and overrules Claude, and blind-labels another sample
    x = rv["items"][0]
    mgr.add_label(rid, x["turn_idx"], x["sample_idx"], x["classifier"], "review:Dhiraj Sah")
    y = rv["items"][5]
    mgr.add_label(rid, y["turn_idx"], y["sample_idx"], "refuse", "human")
    final = {(l["turn_idx"], l["sample_idx"]): l for l in analyze.final_labels(mgr.store, rid)}
    assert final[(x["turn_idx"], x["sample_idx"])]["labeller"] == "review:Dhiraj Sah"
    assert final[(x["turn_idx"], x["sample_idx"])]["label"] == x["classifier"]
    assert final[(y["turn_idx"], y["sample_idx"])]["labeller"] == "human"      # human beats claude
    assert len(final) == len(band)                                              # one label per sample
    rv2 = mgr.review(rid, 40)
    assert rv2["unreviewed"] == 2 and rv2["sources"]["reviewed"] == 1 and rv2["sources"]["human"] == 1
    it = next(i for i in rv2["items"] if (i["turn_idx"], i["sample_idx"]) == (x["turn_idx"], x["sample_idx"]))
    assert it["review"] == x["classifier"] and it["review_by"] == "Dhiraj Sah"
    # reviewed-but-flagged items sort after the unreviewed flagged ones
    assert [i["review"] is None for i in rv2["items"][:3]] == [True, True, False]
    # kappa is computed on final labels, one per sample, and is a number
    assert isinstance(analyze.kappa_for_run(mgr.store, rid), float)
