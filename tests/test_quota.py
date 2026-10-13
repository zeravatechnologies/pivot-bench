"""Free-tier daily counter (Andrej, 2026-09-21): count every Gemini request,
roll over at midnight Pacific, and refuse to start a run that does not fit."""
import datetime as dt
import os

import pytest

from mbench.quota import PACIFIC, DailyQuota, QuotaExceeded
from mbench.orchestrator import Orchestrator
from mbench.providers import GeminiAdapter
from mbench.store import Store
from tests.test_engine import ROOT, _cfg


class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


def test_counter_counts_and_rolls_over_at_midnight_pacific(tmp_path):
    clk = Clock(dt.datetime(2026, 9, 21, 23, 50, tzinfo=PACIFIC))
    q = DailyQuota(str(tmp_path / "q.json"), limit=250, now=clk)
    assert q.remaining() == 250
    assert q.record(55) == 195
    q.record(55)
    assert q.status()["used"] == 110
    q.require(60)
    with pytest.raises(QuotaExceeded):
        q.require(200)
    clk.t = dt.datetime(2026, 9, 22, 0, 1, tzinfo=PACIFIC)     # Google resets here
    assert q.used() == 0 and q.remaining() == 250
    # a second instance on the same file sees the same count (web app + engine)
    q.record(3)
    q2 = DailyQuota(str(tmp_path / "q.json"), limit=250, now=clk)
    assert q2.used() == 3


def test_gemini_adapter_counts_every_attempt(tmp_path, monkeypatch):
    q = DailyQuota(str(tmp_path / "q.json"), limit=10)
    ad = GeminiAdapter("gemini/x", "x", "not-a-real-key", retries=2)
    ad.quota = q
    import urllib.request

    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)
    res = ad.generate([{"role": "user", "content": "hi"}], seed=1, max_tokens=5)
    assert res.error and q.used() == 2          # both attempts counted, like Google does


def test_run_refuses_to_start_when_it_would_not_fit(tmp_path):
    db = str(tmp_path / "t.db")
    qpath = str(tmp_path / "quota.json")
    cfg = _cfg(db, quota={"gemini": {"limit": 250, "path": qpath}})
    adv = GeminiAdapter("gemini/gemini-2.5-flash", "gemini-2.5-flash", "not-a-real-key")
    orch = Orchestrator(cfg, ROOT, store=Store(db), adversary=adv)
    need = orch.expected_quota_calls()
    # local profile, narcissist, live bridges: praise 10 + descent 15 + random 30 = 55, plus margin
    assert 55 < need <= 70
    orch.quota.record(250 - need + 1)          # one short
    with pytest.raises(QuotaExceeded):
        orch.start("blocked")
    assert orch.store.runs() == []               # nothing was created
    # a scripted-bridge run needs no Gemini calls at all
    cfg2 = _cfg(db, quota={"gemini": {"limit": 250, "path": qpath}})
    cfg2["adversary"]["live_bridge"] = False
    o2 = Orchestrator(cfg2, ROOT, store=Store(db), adversary=adv)
    assert o2.expected_quota_calls() == 0
