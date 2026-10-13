"""The installed application: user data folder, version stamp, llama detection, about endpoint."""
import json
import os

import yaml

from mbench import llama_check, paths
from mbench.version import VERSION, about
from tests.test_engine import ROOT


def test_user_config_points_into_the_data_folder(tmp_path):
    data = str(tmp_path / "data")
    cfg_path = paths.ensure_user_config(ROOT, data)
    assert os.path.exists(cfg_path) and os.path.isdir(os.path.join(data, "runs"))
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    assert cfg["store"]["db"] == os.path.join(data, "runs", "mbench.sqlite")
    assert cfg["quota"]["gemini"]["path"] == os.path.join(data, "runs", "quota_gemini.json")
    assert cfg["ladder"] == "ladders/H_hostile.yaml"          # ladders stay relative to the install root
    # second call leaves the user's file alone
    open(cfg_path, "a", encoding="utf-8").write("# edited by the user\n")
    paths.ensure_user_config(ROOT, data)
    assert "edited by the user" in open(cfg_path, encoding="utf-8").read()


def test_user_data_dir_follows_the_platform(monkeypatch):
    monkeypatch.setenv("PIVOT_DATA_DIR", "/tmp/x")
    assert paths.user_data_dir() == "/tmp/x"
    monkeypatch.delenv("PIVOT_DATA_DIR")
    d = paths.user_data_dir()
    assert ("Pivot Benchmark" in d) or ("pivot-benchmark" in d)


def test_about_lists_frozen_ladders():
    a = about(ROOT)
    assert a["version"] == VERSION and a["name"] == "Pivot Benchmark"
    ids = {l["ladder_id"]: l for l in a["ladders"]}
    assert "H_hostile" in ids and len(ids["H_hostile"]["sha256"]) == 16


def test_llama_status_when_nothing_is_running():
    s = llama_check.status("http://127.0.0.1:1")          # port 1: nothing listens
    assert s["reachable"] is False and s["models"] == []
    assert s["releases_url"].startswith("https://github.com/") and "what" in s["help"]
    assert s["platform"] in ("windows", "linux")


def test_run_config_carries_the_app_version(tmp_path):
    from mbench.orchestrator import Orchestrator
    from mbench.store import Store
    from tests.test_engine import _cfg
    cfg = _cfg(str(tmp_path / "t.db")); cfg["adversary"]["live_bridge"] = False
    store = Store(str(tmp_path / "t.db"))
    rid = Orchestrator(cfg, ROOT, store=store).start("v")
    row = store.run(rid)
    stored = json.loads(row["config_json"])
    assert stored["app_version"] == VERSION


def test_web_about_and_llama_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from mbench.manager import RunManager
    from mbench.webapp import create_app
    from tests.test_engine import _cfg
    cfg = _cfg(str(tmp_path / "t.db"))
    p = tmp_path / "config.yaml"; p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    client = TestClient(create_app(RunManager(ROOT, str(p))))
    a = client.get("/api/about").json()
    assert a["version"] == VERSION and any(l["ladder_id"] == "H_hostile" for l in a["ladders"])
    s = client.get("/api/llama").json()
    assert "reachable" in s and "help" in s
