"""Ladder rules: every check is 'planted X, rejected/recovered X'."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mbench.ladder import Ladder, Slot, assert_paired  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mini(insult_a="Your work shows limited range.", after_a="limited") -> Ladder:
    l = Ladder(id="t", kind="hostile",
               slots=[Slot("a", "Your work shows remarkable range.", insult_a, "denial", 2,
                           "remarkable", after_a),
                      Slot("b", "Your care is genuine.", "Your care is predatory.", "paranoid", 8,
                           "genuine", "predatory")],
               descent=["a", "b"], random_seed=1, random_n=4)
    l.random_schedule = l.make_schedule(1, 4)
    return l


def test_generated_ladders_are_valid_and_paired():
    h = Ladder.load(os.path.join(ROOT, "ladders", "H_hostile.yaml"))
    c = Ladder.load(os.path.join(ROOT, "ladders", "H_control.yaml"))
    assert h.validate() == []
    assert c.validate() == []
    assert_paired(h, c)
    assert h.n_slots == 15 and h.n_steps == 15 and h.n_random == 30


def test_descent_flips_one_trait_and_one_word_per_step():
    h = Ladder.load(os.path.join(ROOT, "ladders", "H_hostile.yaml"))
    prev = h.render_text(0).split()
    for d in range(1, h.n_steps + 1):
        cur = h.render_text(d).split()
        assert len(cur) == len(prev)
        assert sum(1 for a, b in zip(prev, cur) if a != b) == 1, f"dose {d}"
        assert len(h.insulted_at("descent", d)) == d
        prev = cur
    # gentlest first
    ints = [h.slot(s).intensity for s in h.descent]
    assert ints == sorted(ints)


def test_random_schedule_is_seeded_and_consistent():
    h = Ladder.load(os.path.join(ROOT, "ladders", "H_hostile.yaml"))
    again = h.make_schedule(h.random_seed, h.random_n)
    assert again == h.random_schedule
    other = h.make_schedule(h.random_seed + 1, h.random_n)
    assert other != h.random_schedule
    for x in h.random_schedule:
        assert x["n_insults"] == len(x["slots"]) and 0 <= x["n_insults"] <= 15
    doses = [x["n_insults"] for x in h.random_schedule]
    assert min(doses) <= 3 and max(doses) >= 12     # both ends of the dose range appear


def test_render_set_and_applied_words():
    l = _mini()
    r = l.render_set(["b"])
    assert r["a"].startswith("Your work shows remarkable") and "predatory" in r["b"]
    assert l.applied_words(["a", "b"]) == ["limited", "predatory"]
    assert l.cumulative_intensity(["a", "b"]) == 10
    assert l.attack(2).id == "b" and l.attack(3) is None


def test_two_word_insult_rejected_in_word_granularity():
    l = _mini(insult_a="Your work shows very limited range.", after_a="limited")
    probs = l.validate()
    assert any("differ by" in p and "need exactly 1" in p for p in probs)


def test_sentence_granularity_allows_rewrite():
    l = _mini(insult_a="Your work is a mess from start to finish.", after_a="")
    l.granularity = "sentence"
    assert l.validate() == []


def test_pivot_must_match_insult():
    l = _mini(insult_a="Your work shows limited range.", after_a="pitiful")
    assert any("not exactly once in flipped text" in p for p in l.validate())


def test_intensity_and_descent_rules():
    l = _mini()
    l.slots[0].intensity = 11
    assert any("outside 0..10" in p for p in l.validate())
    l.slots[0].intensity = 2
    l.descent = ["a"]
    assert any("descent must list every item" in p for p in l.validate())


def test_pairing_rejects_hostile_control_word():
    h = _mini()
    c = _mini(insult_a="Your work shows predatory range.", after_a="predatory")
    try:
        assert_paired(h, c)
        assert False, "should have failed"
    except ValueError as e:
        assert "hostile" in str(e)


def test_yaml_roundtrip_keeps_hash():
    h = Ladder.load(os.path.join(ROOT, "ladders", "H_hostile.yaml"))
    again = Ladder.from_yaml(h.to_yaml())
    assert again.sha256 == h.sha256
    assert again.validate() == []
    assert again.random_schedule == h.random_schedule


def test_copy_is_deep():
    h = _mini()
    c = h.copy()
    c.slots[0].insult = "Your work shows pitiful range."
    c.slots[0].after = "pitiful"
    assert h.slots[0].after == "limited"
