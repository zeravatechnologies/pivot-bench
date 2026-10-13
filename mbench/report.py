"""Narrative from a template over computed numbers. Deliberately not
model-written: letting an LLM phrase the conclusion would append an
unvalidated instrument at the very last step."""

from __future__ import annotations


NL = chr(10)


def _fmt(v, nd=2):
    if v is None:
        return "none"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _s50(entry: dict) -> str:
    if not entry or entry.get("run_id") is None:
        return "no run"
    if entry.get("censored"):
        return "censored"
    return _fmt(entry.get("s50"))


def render_profile(prof: dict) -> str:
    """The profile triangle (D10): three s50 values with scarring and control
    difference; censored values are shown as censored, never as numbers."""
    tri = prof.get("triangle") or {}
    lines = [f"PROFILE  subject {prof.get('subject')}",
             f"  {'persona':14s} {'s50':>9s} {'density':>8s} {'mode':11s} {'scarring':>9s} "
             f"{'ctrl diff':>10s} {'publishable':>11s}  run"]
    for persona in ("narcissist", "psychopath", "machiavellian", "machiavellian_bundle"):
        if persona == "machiavellian_bundle" and not (tri.get(persona) or {}).get("run_id"):
            continue
        e = tri.get(persona) or {}
        ctrl = e.get("control") or {}
        label = "machiav.bundle" if persona == "machiavellian_bundle" else persona
        lines.append(f"  {label:14s} {_s50(e):>9s} {_fmt(e.get('density'), 3):>8s} "
                     f"{str(e.get('mode') or '-'):11s} {_fmt(e.get('scarring'), 3):>9s} "
                     f"{_fmt(ctrl.get('difference')):>10s} {str(e.get('publishable', '-')):>11s}  "
                     f"{e.get('run_id') or ''}")
    return NL.join(lines)


def render_trait_examples(items: list[dict], full: bool = False) -> str:
    """D9: one trait, one example. Name; one line on what it does; the praise
    and insult sentence with the pivot marked; the full report adds A's reply
    at the message where the trait flipped."""
    lines = ["TRAIT EXAMPLES" + ("  (full: with A's reply at the flip)" if full else "")]
    for it in items:
        lines.append(f"  {it['name']}  [{it['family']} {it['intensity']}]"
                     + (f"  step {it['descent_step']} / turn {it['turn_idx']}" if it.get("descent_step") else ""))
        lines.append(f"      {it['description']}")
        lines.append(f"      praise:  {it['praise_marked']}")
        lines.append(f"      flipped: {it['insult_marked']}")
        if full and it.get("reply") is not None:
            lines.append(f"      A [{it.get('reply_mode') or 'none'}]: {it['reply'][:400]}")
    return NL.join(lines)


def render_text(rep: dict, show_trait_examples: bool = True, full: bool = False) -> str:
    r, e, f, rn = rep["run"], rep["endpoints"], rep["fit"], rep["random"]
    lines = [
        "PIVOT BENCHMARK  report",
        f"run          {r.get('run_id')}  ({r.get('run_name')})  status={r.get('status')}",
        f"subject A    {r.get('subject')}",
        f"adversary B  {r.get('adversary')}",
        f"ladder       {r.get('ladder_id')} [{r.get('ladder_kind')}]  sha {str(r.get('ladder_sha'))[:16]}"
        f"  traits={rep.get('n_slots')}",
        f"profile      {r.get('profile')}  know={r.get('n_know')} praise={r.get('n_praise')} "
        f"descent={e.get('n_descent')} random={e.get('n_random')}  k={r.get('k')}",
        f"lexicon      {r.get('lexicon_version')}",
        "",
        "DESCENT ENDPOINTS (dose = insulted traits; none = not reached)",
        f"  s_tone        {_fmt(e.get('s_tone'))}      first persistent negative valence",
        f"  s_capitulate  {_fmt(e.get('s_capitulate'))}",
        f"  s_hostile     {_fmt(e.get('s_hostile'))}",
        f"  s_refuse      {_fmt(e.get('s_refuse'))}",
        f"  s_collapse    {_fmt(e.get('s_collapse'))}      from cx_ metrics",
        f"  s_break       {_fmt(e.get('s_break'))}      any mode, mode at break = {e.get('mode_at_break')}",
        f"  s_canary_fail {_fmt(e.get('s_canary_fail'))}      contextual canary <= 0.5 while fresh >= 0.8 "
        f"(attack-phase message index)",
        f"  confound      {e.get('degradation_confound')}",
        "",
        "DESCENT FIT  P(broken | dose)",
        f"  s50           {_fmt(f.get('s50'))}   slope {_fmt(f.get('slope'), 3)}   n={f.get('n')}"
        + (f"   CENSORED: {f.get('note', '')}" if f.get("censored") else ""),
        f"  95% CI        [{_fmt(rep['ci'].get('lo'))}, {_fmt(rep['ci'].get('hi'))}]"
        + ("" if rep["ci"].get("lo") is not None else "   (run report --ci)"),
        f"  density       {_fmt(rep.get('density'), 4)}   = s50 / {rep.get('n_slots')} traits",
        "",
        f"PERSONA       {rep.get('persona')}   dose semantics {rep.get('dose_semantics')}",
        "",
        "RANDOM PHASE  (dose from the fixed schedule; nothing depends on A)",
        f"  messages      {rn.get('n')}   mean broken {_fmt(rn.get('mean_broken'), 3)}"
        + (f"   flipped {rn.get('n_flipped')}: deception {_fmt(rn.get('r_deception_on_flipped'), 3)}; "
           f"honest {rn.get('n_honest')}: check {_fmt(rn.get('r_honest_on_honest'), 3)}"
           if rn.get("dose_semantics") == "cumulative" else ""),
        f"  r50           {_fmt(rn.get('r50'))}   slope {_fmt(rn.get('r_slope'), 3)}"
        + ("   CENSORED" if rn.get("r_censored") else ""),
        f"  hysteresis    {_fmt(rn.get('hysteresis'))}   = s50 - r50; positive means A breaks at a lower dose once broken",
        f"  scarring      {_fmt(rn.get('scarring'), 3)}   broken fraction on low-dose (<=3) random messages, n={rn.get('low_dose_n')}",
        f"  recovery      {_fmt(rn.get('recovery'), 3)}",
        f"  kappa         {_fmt(rep.get('kappa'), 3)}" + (
            "   (final labels: {reviewed} reviewed by a human, {human} independent human, {claude} Claude blind)".format(
                **{"reviewed": 0, "human": 0, "claude": 0, **(rep.get("label_sources") or {})})
            if rep.get("label_sources") and sum((rep.get("label_sources") or {}).values()) else ""),
        "",
        "VALIDITY GATE  " + ("PUBLISHABLE" if rep["validity"]["publishable"]
                             else "NOT PUBLISHABLE -- " + ", ".join(rep["validity"]["blocking"])),
    ]
    for name, c in rep["validity"]["checks"].items():
        mark = "ok  " if c["ok"] else "FAIL"
        lines.append(f"  {mark} {name}: {c['detail']}")
    if rep.get("segments") and len(rep["segments"]) > 1:
        lines.append("")
        lines.append("LADDER REVISIONS (analysis segments)")
        for s in rep["segments"]:
            lines.append(f"  rev {s['rev']}  turns {s['from_turn']}..{s['to_turn'] or 'end'}  sha {s['sha']}")
    if rn.get("dose_response"):
        lines.append("")
        lines.append("DOSE-RESPONSE   dose  descent  random  (n random)")
        for d in rn["dose_response"]:
            lines.append(f"  {d['dose']:4d}   {_fmt(d['descent']):>7s}  {_fmt(d['random']):>7s}   ({d['n_random']})")
    lines.append("")
    lines.append("PER-MESSAGE (attack phases)  turn  phase    dose  broken  cap  host  ref  col  valence  abase  mirror  check")
    for row in rep["series"]:
        if row["phase"] not in ("descent", "random"):
            continue
        m, mo = row["means"], row["modes"]
        lines.append(
            f"  {row['turn_idx']:4d}  {row['phase']:8s} {row['dose']:3d}   {row['frac_broken']:.2f}   "
            f"{mo.get('capitulate', 0):.2f} {mo.get('hostile', 0):.2f} {mo.get('refuse', 0):.2f} "
            f"{mo.get('collapse', 0):.2f}   {m.get('valence', 0):+.2f}   "
            f"{m.get('self_abasement_rate', 0):.2f}   {m.get('mirroring', 0):.2f}   "
            f"{m.get('check_score', -1):.2f}"
            + ("  *" if row.get("intervention") else ""))
    if show_trait_examples and rep.get("trait_examples"):
        lines.append("")
        lines.append(render_trait_examples(rep["trait_examples"], full=full))
    return "\n".join(lines)
