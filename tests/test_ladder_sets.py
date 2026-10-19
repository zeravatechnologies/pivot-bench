import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mbench.ladder import Ladder  # noqa: E402
from mbench.ladder_sets import LadderSets  # noqa: E402
from mbench.store import Store  # noqa: E402


def test_manifest_matches_files_and_resolves_every_ladder():
    sets = LadderSets.load(ROOT)
    assert sets.current == "ladders-v1"
    assert sets.check() == []                                   # files on disk are the recorded set
    for name in os.listdir(os.path.join(ROOT, "ladders")):
        if name.endswith(".yaml") and name != "manifest.yaml":
            l = Ladder.load(os.path.join(ROOT, "ladders", name))
            assert sets.resolve(l.sha256) == "ladders-v1"
    assert sets.resolve("0" * 64) is None                       # an unknown ladder belongs to no set


def test_store_migration_and_backfill(tmp_path):
    st = Store(os.path.join(str(tmp_path), "t.sqlite"))
    sets = LadderSets.load(ROOT)
    h = Ladder.load(os.path.join(ROOT, "ladders", "H_hostile.yaml"))
    st.new_run("r1", run_name="old run without a set", ladder_id="H_hostile", ladder_kind="hostile", ladder_sha=h.sha256)
    st.new_run("r2", run_name="new run", ladder_id="H_hostile", ladder_kind="hostile", ladder_sha=h.sha256, ladder_set="ladders-v1")
    st.new_run("r3", run_name="unknown ladder", ladder_id="X_hostile", ladder_kind="hostile", ladder_sha="f" * 64)
    out = sets.backfill(st)
    assert out == {"set": 1, "unresolved": 1, "already": 1}
    by = {r["run_id"]: r.get("ladder_set") for r in st.runs()}
    assert by == {"r1": "ladders-v1", "r2": "ladders-v1", "r3": None}
