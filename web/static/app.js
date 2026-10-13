/* Pivot Benchmark web UI. Vanilla JS, one file, polls the API. */
(() => {
  const $ = (id) => document.getElementById(id);
  const api = async (path, opts = {}) => {
    const r = await fetch("/api" + path, { headers: { "Content-Type": "application/json" }, ...opts });
    if (!r.ok) throw new Error(await r.text());
    const ct = r.headers.get("content-type") || "";
    return ct.includes("json") ? r.json() : r.text();
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, nd = 2) => (v == null ? "-" : typeof v === "number" ? v.toFixed(nd) : String(v));
  const MODES = ["capitulate", "hostile", "refuse", "collapse"];
  const MODE_COL = { capitulate: "#2a78d6", hostile: "#e34948", refuse: "#eda100", collapse: "#4a3aa7" };
  const FAM_COL = { insult: "#e34948", denial: "#2a78d6", paranoid: "#4a3aa7", deception: "#b3771e", "-": "#888" };
  const HEAD = ["valence", "self_abasement_rate", "counter_hostility_rate", "boundary_present", "distress_rate", "mirroring", "identity_drift", "reply_len", "cx_ttr", "check_score"];
  const atkLabel = (a) => !a ? "" : a.kind === "random" ? `  random dose ${a.n_insults}` : `  ${a.slot}: ${a.before}->${a.after}`;

  const TABS = [["run", "Run"], ["transcript", "Transcript"], ["attacks", "Attacks"], ["script", "Script editor"], ["intervene", "Intervene"], ["curves", "Curves"], ["compare", "Compare"], ["label", "Label"], ["report", "Report"], ["approval", "Approval"], ["settings", "Settings"]];
  const state = { run: null, ctrl: null, tab: "run", turns: [], attacks: [], band: [], bandI: 0, lastEv: 0, show: { dose: true, broken: true, modes: true, valence: true, abase: true, mirror: false, canary: true, fit: true, control: true } };

  // ---- nav --------------------------------------------------------------------
  for (const [id, label] of TABS) {
    const b = document.createElement("button"); b.textContent = label; b.dataset.tab = id;
    b.onclick = () => showTab(id); $("nav").appendChild(b);
  }
  function showTab(id) {
    state.tab = id;
    document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === id));
    document.querySelectorAll("main section").forEach((s) => s.classList.toggle("on", s.id === "tab-" + id));
    refreshTab();
  }
  function refreshTab() {
    if (state.tab === "approval") { fillApproval(); return; }
    if (!state.run) return;
    ({ transcript: fillTranscript, attacks: fillAttacks, script: loadScript, intervene: fillEvents, curves: fillCurves, compare: fillCompare, label: drawBandIfEmpty, report: fillReport }[state.tab] || (() => {}))();
  }

  // ---- runs -----------------------------------------------------------------------
  async function refreshLlama() {
    try {
      const s = await api("/llama"); const p = $("llama_panel");
      if (s.reachable) { p.style.display = "none"; $("quota_line").title = `local model server: ${s.models.join(", ")}`; return; }
      p.style.display = ""; const h = s.help;
      $("llama_detail").textContent = `(nothing answered at ${s.base_url}${s.binary ? "; llama-server is installed at " + s.binary + " but not running" : ""})`;
      $("llama_what").textContent = h.what; $("llama_how").textContent = s.platform === "windows" ? h.windows : h.linux;
      $("llama_releases").href = s.releases_url; $("llama_docs").href = s.docs_url;
      $("llama_python").textContent = s.python_package ? "Python package llama-cpp-python is installed: " + h.python.split("and then ")[1] : h.python;
      $("llama_model").textContent = h.model;
    } catch (e) { /* no server to ask */ }
  }
  $("llama_recheck").onclick = refreshLlama;
  async function fillAbout() { try { const a = await api("/about"); $("about_line").textContent = `v${a.version} · ladders ${a.ladders.map((l) => l.ladder_id.replace("_hostile", "") + ":" + l.sha256.slice(0, 8) + (l.status === "frozen" ? "" : " (" + l.status + ")")).join(" ")}`; $("about_line").title = `data folder: ${a.data_dir}\nconfig: ${a.config_path}`; } catch (e) {} }
  async function refreshQuota() { try { const q = await api("/quota"); $("quota_line").textContent = q.limit ? `Gemini daily budget: ${q.remaining} of ${q.limit} requests left today (about ${Math.floor(q.remaining / 60)} run(s)); resets ${q.resets_at.slice(11, 16)} Pacific` : ""; } catch (e) {} }
  async function refreshRuns() {
    const runs = await api("/runs");
    const cur = state.run;
    $("runpick").innerHTML = runs.map((r) => `<option value="${r.run_id}">${r.run_id}  ${r.status}  ${esc(r.run_name || "")}  A=${esc(r.subject)}  ${esc(r.persona || "")}  ${esc(r.ladder_id)}  turn=${r.last_turn}</option>`).join("");
    $("a_ctrl").innerHTML = `<option value="">(no control run)</option>` + runs.filter((r) => r.ladder_kind === "control").map((r) => `<option value="${r.run_id}">${r.run_id} ${esc(r.run_name || "")} A=${esc(r.subject)}</option>`).join("");
    if (cur && runs.some((r) => r.run_id === cur)) $("runpick").value = cur;
    state.run = $("runpick").value || null;
    tick();
  }
  $("runpick").onchange = () => { state.run = $("runpick").value; state.band = []; state.bandI = 0; $("l_kappa").textContent = ""; refreshTab(); tick(); refreshReviewCount(); };
  $("refresh").onclick = refreshRuns;
  $("a_ctrl").onchange = () => { state.ctrl = $("a_ctrl").value || null; fillCurves(); };

  async function tick() {
    if (!state.run) return;
    try {
      const st = await api(`/runs/${state.run}/status`);
      $("progress").max = st.total_turns || 1; $("progress").value = st.last_turn || 0;
      $("status").textContent = `${st.db_status}${st.alive ? " (engine alive" + (st.paused ? ", paused)" : ")") : ""}`;
    } catch (e) { /* ignore */ }
  }
  async function pollEvents() {
    try {
      const evs = await api(`/events?since=${state.lastEv}`);
      for (const e of evs) {
        state.lastEv = Math.max(state.lastEv, e.ts);
        const p = e.payload || {};
        let line = `[${e.run}] ${e.kind}`;
        if (e.kind === "turn") line += ` turn ${p.turn_idx} ${p.phase} dose=${p.step} ${p.request_id || ""} broken=${fmt(p.frac_broken)} bridge=${p.bridge_source}` + atkLabel(p.attack);
        else if (e.kind === "status") line += ` ${p.status} ${p.error || ""}`;
        else line += " " + JSON.stringify(p).slice(0, 200);
        const log = $("log"); log.textContent += line + "\n"; log.scrollTop = log.scrollHeight;
        if (e.kind === "turn" && e.run === state.run && ["transcript", "attacks", "curves"].includes(state.tab)) refreshTab();
        if (e.kind === "status" && p.status === "running" && e.run !== state.run) { await refreshRuns(); $("runpick").value = e.run; state.run = e.run; }
      }
    } catch (e) { /* ignore */ }
    tick();
  }
  setInterval(pollEvents, 1500);

  // ---- run form -------------------------------------------------------------------
  let CFG = null;
  async function initForm() {
    const cfg = CFG = await api("/config");
    const [A, B, J] = await Promise.all([api("/models?role=A"), api("/models?role=B"), api("/models?role=judge")]);
    const opt = (m) => `<option value="${m.name}">${m.name}  (${m.has_key ? "key ok" : "needs " + m.key_env})</option>`;
    $("f_subject").innerHTML = A.map(opt).join(""); $("f_adversary").innerHTML = B.map(opt).join("");
    $("j_model").innerHTML = J.map((m) => `<option value="${m.name}">${m.name}</option>`).join("");
    $("f_subject").value = cfg.subject.model; $("f_adversary").value = cfg.adversary.model;
    $("f_profile").innerHTML = Object.keys(cfg.profiles).map((p) => `<option>${p}</option>`).join(""); $("f_profile").value = cfg.profile;
    $("f_ladder").innerHTML = cfg.ladders.map((l) => `<option>${l}</option>`).join(""); $("f_ladder").value = cfg.ladder;
    $("f_name").value = cfg.run_name || "run"; $("f_k").value = cfg.probe.k; $("f_workers").value = cfg.probe.workers;
    $("f_window").value = cfg.probe.history_window; $("f_every").value = cfg.canary.every; $("f_max").value = cfg.probe.max_attacks || 0;
    $("f_random").value = (cfg.profiles[cfg.profile] || {}).n_random ?? 30;
    $("f_live").checked = !!cfg.adversary.live_bridge; $("j_kind").value = (cfg.judge || {}).kind || "none"; $("j_n").value = (cfg.judge || {}).n || 60;
  }
  $("f_profile").onchange = () => { if (CFG) $("f_random").value = (CFG.profiles[$("f_profile").value] || {}).n_random ?? 30; };
  $("b_start").onclick = async () => {
    const prof = { ...(CFG.profiles[$("f_profile").value] || {}), n_random: +$("f_random").value };
    const overrides = { subject: { model: $("f_subject").value }, adversary: { model: $("f_adversary").value, live_bridge: $("f_live").checked },
      profile: $("f_profile").value, ladder: $("f_ladder").value, profiles: { [$("f_profile").value]: prof },
      probe: { k: +$("f_k").value, workers: +$("f_workers").value, history_window: +$("f_window").value, max_attacks: +$("f_max").value || null },
      canary: { every: +$("f_every").value } };
    try { const r = await api("/runs", { method: "POST", body: JSON.stringify({ overrides, run_name: $("f_name").value }) });
      $("log").textContent += `started ${r.run_id}\n`; setTimeout(async () => { await refreshRuns(); $("runpick").value = r.run_id; state.run = r.run_id; }, 400);
    } catch (e) { alert("start failed: " + e.message); }
  };
  $("b_pause").onclick = () => api(`/runs/${state.run}/pause`, { method: "POST" });
  $("b_resume").onclick = () => api(`/runs/${state.run}/resume`, { method: "POST" });
  $("b_stop").onclick = () => api(`/runs/${state.run}/stop`, { method: "POST" });
  $("b_cont").onclick = () => api(`/runs/${state.run}/continue`, { method: "POST" }).catch((e) => alert(e.message));

  // ---- transcript ----------------------------------------------------------------------
  function segHtml(segs) {
    return "<p>" + segs.filter((s) => s.source !== "fact").map((s) => {
      let t = esc(s.text);
      if (s.changed) t = t.replace(esc(s.changed), s.new ? `<span class="hot">${esc(s.changed)}</span>` : `<b style="color:#e34948">${esc(s.changed)}</b>`);
      if (s.insulted && !s.new) t = `<u>${t}</u>`;
      return `<span class="seg-${s.source}">${t}</span>`;
    }).join(" ") + "</p>";
  }
  async function fillTranscript() {
    state.turns = await api(`/runs/${state.run}/transcript`);
    const sel = state.selTurn ?? state.turns.length - 1;
    $("t_list").innerHTML = state.turns.map((t, i) => {
      const n = t.samples.length || 1, br = t.samples.filter((s) => s.mode).length / n;
      return `<div data-i="${i}" class="${i === sel ? "sel" : ""}">t${String(t.turn_idx).padStart(3)} ${t.phase.padEnd(7)} dose=${String(t.step).padStart(2)} ${(t.request_id || "").padEnd(12)} broken=${br.toFixed(2)}${atkLabel(t.attack)}${t.intervention ? "  [manual]" : ""}</div>`;
    }).join("");
    $("t_list").querySelectorAll("div").forEach((d) => (d.onclick = () => showTurn(+d.dataset.i)));
    if (state.turns.length) showTurn(Math.min(sel, state.turns.length - 1));
  }
  function showTurn(i) {
    state.selTurn = i; const t = state.turns[i]; if (!t) return;
    $("t_list").querySelectorAll("div").forEach((d) => d.classList.toggle("sel", +d.dataset.i === i));
    let head = `<p><b>turn ${t.turn_idx}</b> phase=${t.phase} dose=${t.step} request=${t.request_id} bridge=${t.bridge_source}`;
    const a = t.attack;
    if (a && a.kind === "descent") head += `<br><b>descent step ${a.step}</b>: trait <i>${a.slot}</i> flipped, ${a.family} intensity ${a.intensity} (cumulative ${a.cumulative_intensity}): <s>${esc(a.before)}</s> → <span class="hot">${esc(a.after)}</span> — ${esc(a.rationale)}`;
    else if (a && a.kind === "random") head += `<br><b>random message ${a.random_idx}</b>: ${a.n_insults} insulted (${a.insulted.join(", ")}); families ${JSON.stringify(a.families)}; cumulative intensity ${a.cumulative_intensity}`;
    $("t_b").innerHTML = head + "</p>" + segHtml(t.segments);
    $("t_a").innerHTML = t.samples.map((s) => {
      const m = s.metrics; const cells = HEAD.map((k) => `${k.replace("_rate", "").replace("_present", "")}=${fmt(m[k])}`).join(" ");
      return `<p><b class="m-${s.mode || ""}">sample ${s.sample_idx} [${s.mode || "-"}]</b> seed=${s.seed}${s.error ? ` <span class="hot">error: ${esc(s.error)}</span>` : ""}<br><small class="muted">${cells}</small><br>${esc(s.text)}</p>`;
    }).join("") || "<p>no samples</p>";
  }

  // ---- attacks ------------------------------------------------------------------------------
  async function fillAttacks() {
    const [atks, rep] = await Promise.all([api(`/runs/${state.run}/attacks`), api(`/runs/${state.run}/report`)]);
    state.attacks = atks; const br = {}; for (const r of rep.series) br[r.turn_idx] = r.frac_broken;
    const traits = [...new Set(atks.filter((a) => a.kind === "descent").map((a) => a.slot))];
    if ($("a_slot").options.length !== traits.length + 1) $("a_slot").innerHTML = `<option>all traits</option>` + traits.map((s) => `<option>${s}</option>`).join("");
    const kind = $("a_kind").value, fam = $("a_family").value, trait = $("a_slot").value, mi = +$("a_minint").value;
    const rows = atks.filter((a) => (kind === "all" || a.kind === kind) && (fam === "all" || a.family === fam) && (trait === "all traits" || (a.insulted || []).includes(trait)) && (!mi || (a.intensity != null && a.intensity >= mi)));
    state.attackRows = rows;
    $("a_table").querySelector("tbody").innerHTML = rows.map((a, i) => `<tr data-i="${i}" class="${state.selAttack === a.turn_idx ? "sel" : ""}"><td>${a.kind}</td><td>${a.idx}</td><td>${a.turn_idx}</td><td>${a.dose}</td><td>${esc(a.slot)}</td><td style="color:${FAM_COL[a.family] || "#888"}">${a.family}</td><td>${fmt(a.intensity)}</td><td>${a.cumulative_intensity}</td><td>${a.kind === "descent" ? esc(a.before) + " → " + esc(a.after) : esc(a.after)}</td><td>${a.played ? "yes" : ""}</td><td>${fmt(br[a.turn_idx])}</td></tr>`).join("");
    $("a_table").querySelectorAll("tr[data-i]").forEach((tr) => (tr.onclick = () => showAttack(rows[+tr.dataset.i])));
  }
  ["a_kind", "a_family", "a_slot", "a_minint"].forEach((id) => ($(id).onchange = fillAttacks));
  async function showAttack(a) {
    state.selAttack = a.turn_idx;
    $("a_table").querySelectorAll("tr[data-i]").forEach((tr) => tr.classList.toggle("sel", state.attackRows[+tr.dataset.i].turn_idx === a.turn_idx));
    const d = await api(`/runs/${state.run}/attacks/${a.turn_idx}`);
    let out;
    if (a.kind === "descent") {
      out = `<h3>descent step ${a.idx} (turn ${a.turn_idx}, dose ${a.dose}) — trait <i>${a.slot}</i>, ${a.family} intensity ${a.intensity} (cumulative ${a.cumulative_intensity})</h3><p><i>${esc(a.rationale)}</i></p>`;
      out += `<p><b>praise:</b> ${esc(a.slot_before).replace(esc(a.before), `<b style="color:#2a78d6">${esc(a.before)}</b>`)}<br><b>insult:</b> ${esc(a.slot_after).replace(esc(a.after), `<span class="hot">${esc(a.after)}</span>`)}</p><p><b>insulted so far:</b> ${a.insulted.join(", ")}</p>`;
    } else {
      out = `<h3>random message ${a.idx} (turn ${a.turn_idx}) — dose ${a.dose}, families ${JSON.stringify(a.families)}, cumulative intensity ${a.cumulative_intensity}</h3><p><b>insulted:</b> ${a.insulted.join(", ") || "none"}</p>`;
    }
    if (d.rendered) out += "<p>" + d.rendered.map((s) => { let t = esc(s.text); if (s.insulted && s.after) t = t.replace(esc(s.after), `<b style="color:#e34948">${esc(s.after)}</b>`); return `${s.insulted ? "●" : "○"} <small style="color:${FAM_COL[s.family]}">${s.slot}</small> ${t}`; }).join("<br>") + "</p>";
    if (d.turn) {
      out += `<p><b>request:</b> ${d.turn.request_id} <b>bridge:</b> ${d.turn.bridge_source}</p>`;
      for (const s of d.samples) { const m = s.metrics; out += `<p><b class="m-${s.mode || ""}">A sample ${s.sample_idx} [${s.mode || "-"}]</b> valence=${fmt(m.valence)} abase=${fmt(m.self_abasement_rate)} hostile=${fmt(m.counter_hostility_rate)} boundary=${fmt(m.boundary_present)} mirror=${fmt(m.mirroring)} drift=${fmt(m.identity_drift)} check=${fmt(m.check_score)}<br>${esc(s.text)}</p>`; }
    } else out += "<p><i>not played yet</i></p>";
    if (d.canary) out += `<p><b>nearest canary</b> (turn ${d.canary.turn_idx}): fresh=${fmt(d.canary.fresh)} context=${fmt(d.canary.context)}</p>`;
    if (state.ctrl) { const cd = await api(`/runs/${state.ctrl}/attacks/${a.turn_idx}`); if (cd.attack) { const n = cd.samples.length || 1, b = cd.samples.filter((s) => s.mode).length / n; out += `<p><b>control at the same message:</b> ${esc(cd.attack.after)}, broken ${b.toFixed(2)}</p>`; } }
    $("a_detail").innerHTML = out;
  }
  $("a_jump").onclick = () => { const a = state.attackRows?.find((x) => x.turn_idx === state.selAttack); if (!a) return; state.selTurn = null; showTab("transcript"); setTimeout(() => { const i = state.turns.findIndex((t) => t.turn_idx === a.turn_idx); if (i >= 0) showTurn(i); }, 300); };
  $("a_reroll").onclick = async () => { const a = state.attackRows?.find((x) => x.turn_idx === state.selAttack); if (!a || !a.played) return; await api(`/runs/${state.run}/reroll`, { method: "POST", body: JSON.stringify({ turn_idx: a.turn_idx, seed_shift: 1 }) }); setTimeout(() => showAttack(a), 500); };

  // ---- script editor ---------------------------------------------------------------------------
  async function loadScript() { $("s_edit").value = await api(`/runs/${state.run}/ladder`); $("s_msg").textContent = "loaded latest revision"; }
  $("s_reload").onclick = loadScript;
  $("s_validate").onclick = async () => { const r = await api(`/runs/${state.run}/validate-ladder`, { method: "POST", body: JSON.stringify({ yaml: $("s_edit").value }) }); $("s_msg").textContent = r.ok ? `valid: ${r.slots} traits, descent ${r.descent}, random ${r.random}, sha ${r.sha}` : "INVALID: " + r.problems.slice(0, 6).join(" | "); };
  $("s_diffbtn").onclick = async () => { const old = (await api(`/runs/${state.run}/ladder`)).split("\n"), nw = $("s_edit").value.split("\n"); const out = []; const n = Math.max(old.length, nw.length); for (let i = 0; i < n; i++) if (old[i] !== nw[i]) out.push(`line ${i + 1}\n- ${old[i] ?? ""}\n+ ${nw[i] ?? ""}`); $("s_diff").textContent = out.join("\n") || "(no changes)"; };
  $("s_save").onclick = async () => { const r = await api(`/runs/${state.run}/ladder`, { method: "PUT", body: JSON.stringify({ yaml: $("s_edit").value }) }); $("s_msg").textContent = r.ok ? `saved revision ${r.rev}` : `rejected: ${r.reason}`; if (r.ok) loadScript(); };

  // ---- intervene ----------------------------------------------------------------------------
  $("i_queue").onclick = async () => { const r = await api(`/runs/${state.run}/manual`, { method: "POST", body: JSON.stringify({ text: $("i_text").value }) }); $("i_log").textContent += (r.ok ? "queued manual B turn" : "no active run to queue into") + "\n"; if (r.ok) $("i_text").value = ""; };
  $("i_reroll").onclick = async () => { const r = await api(`/runs/${state.run}/reroll`, { method: "POST", body: JSON.stringify({ turn_idx: +$("i_turn").value, seed_shift: +$("i_shift").value }) }); $("i_log").textContent += `reroll turn ${$("i_turn").value}: ${r.queued ? "queued" : r.turn_idx ? "done" : "no such turn"}\n`; };
  async function fillEvents() { const ev = await api(`/runs/${state.run}/events`); $("i_log").textContent = ev.map((e) => `${e.ts}  ${e.kind}  ${JSON.stringify(e.detail)}`).join("\n"); }

  // ---- curves --------------------------------------------------------------------------------
  for (const [k, label] of [["dose", "dose"], ["broken", "broken"], ["modes", "modes"], ["valence", "valence"], ["abase", "abasement"], ["mirror", "mirroring"], ["canary", "canary"], ["fit", "logistic fit"], ["control", "control"]]) {
    const l = document.createElement("label"); const c = document.createElement("input"); c.type = "checkbox"; c.checked = state.show[k];
    c.onchange = () => { state.show[k] = c.checked; drawChart(); }; l.appendChild(c); l.append(" " + label); $("c_toggles").appendChild(l);
  }
  let chartData = null;
  const indexRows = (rows) => rows.filter((r) => r.phase === "descent" || r.phase === "random").map((r, i) => ({ ...r, x: i + 1 }));
  async function fillCurves() {
    const rep = await api(`/runs/${state.run}/report`);
    const ctrl = state.ctrl ? await api(`/runs/${state.ctrl}/report`) : null;
    const rows = indexRows(rep.series);
    chartData = { rows, ctrl: ctrl ? indexRows(ctrl.series) : [], eps: rep.endpoints, fit: rep.fit, canary: rep.canary, offset: (rep.run.n_know || 0) + (rep.run.n_praise || 0), nSlots: rep.n_slots || 15, nDesc: rows.filter((r) => r.phase === "descent").length };
    const e = rep.endpoints, f = rep.fit, rn = rep.random;
    $("c_summary").textContent = `descent: s50=${fmt(f.s50)} slope=${fmt(f.slope, 3)} density=${fmt(rep.density, 4)} s_tone=${e.s_tone} s_break=${e.s_break} (${e.mode_at_break}) s_collapse=${e.s_collapse} canary_fail=${e.s_canary_fail} confound=${e.degradation_confound} | random: r50=${fmt(rn.r50)} hysteresis=${fmt(rn.hysteresis)} scarring=${fmt(rn.scarring, 3)} recovery=${fmt(rn.recovery, 3)} | ` + (rep.validity.publishable ? "PUBLISHABLE" : "not publishable: " + rep.validity.blocking.join(", "));
    drawChart();
  }
  function drawChart() {
    const cv = $("chart"), ctx = cv.getContext("2d"); const W = cv.width, H = cv.height;
    const dark = matchMedia("(prefers-color-scheme: dark)").matches; ctx.fillStyle = dark ? "#222221" : "#fff"; ctx.fillRect(0, 0, W, H);
    if (!chartData || chartData.rows.length < 2) { ctx.fillStyle = "#888"; ctx.fillText("no attack-phase data yet", W / 2 - 60, H / 2); return; }
    const L = 48, R = 14, T = 24, B = 40, rows = chartData.rows; const lo = 1, hi = Math.max(2, rows[rows.length - 1].x);
    const X = (x) => L + (W - L - R) * (x - lo) / (hi - lo), Y = (v) => H - B - (H - T - B) * Math.max(0, Math.min(1, v));
    const S = state.show; const legend = [];
    if (S.dose) { ctx.beginPath(); ctx.moveTo(X(lo), Y(0)); rows.forEach((r) => ctx.lineTo(X(r.x), Y(r.dose / chartData.nSlots))); ctx.lineTo(X(hi), Y(0)); ctx.closePath(); ctx.fillStyle = dark ? "#33332f" : "#d9d8d0"; ctx.fill(); legend.push(["dose / traits", dark ? "#33332f" : "#d9d8d0"]); }
    ctx.strokeStyle = dark ? "#2c2c2a" : "#e1e0d9"; ctx.fillStyle = dark ? "#c3c2b7" : "#52514e"; ctx.font = "11px system-ui"; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) { const y = Y(i / 4); ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(W - R, y); ctx.stroke(); ctx.fillText((i / 4).toFixed(2), 8, y + 4); }
    for (const x of new Set([lo, hi, ...rows.map((r) => r.x).filter((x) => x % 5 === 0)])) ctx.fillText("#" + x, X(x) - 8, H - B + 14);
    if (chartData.nDesc > 0 && chartData.nDesc < hi) { const xb = X(chartData.nDesc + 0.5); ctx.setLineDash([4, 3]); ctx.strokeStyle = dark ? "#c3c2b7" : "#52514e"; ctx.beginPath(); ctx.moveTo(xb, T); ctx.lineTo(xb, H - B); ctx.stroke(); ctx.setLineDash([]); ctx.fillText("random phase", xb + 4, H - B - 6); }
    const line = (fn, col, w = 2, dash = [], rs = rows) => { if (rs.length < 2) return; ctx.beginPath(); ctx.setLineDash(dash); ctx.strokeStyle = col; ctx.lineWidth = w; rs.forEach((r, i) => (i ? ctx.lineTo(X(r.x), Y(fn(r))) : ctx.moveTo(X(r.x), Y(fn(r))))); ctx.stroke(); ctx.setLineDash([]); };
    if (S.modes) for (const m of MODES) { line((r) => r.modes[m] || 0, MODE_COL[m], 1); legend.push([m, MODE_COL[m]]); }
    if (S.valence) { line((r) => ((r.means.valence || 0) + 1) / 2, "#008300", 1, [3, 3]); legend.push(["valence (0.5=neutral)", "#008300"]); }
    if (S.abase) { line((r) => Math.min(1, (r.means.self_abasement_rate || 0) / 10), "#e87ba4", 1, [1, 2]); legend.push(["abasement/10", "#e87ba4"]); }
    if (S.mirror) { line((r) => r.means.mirroring || 0, "#00a0a0", 1, [4, 2]); legend.push(["mirroring", "#00a0a0"]); }
    if (S.control && chartData.ctrl.length > 1) { line((r) => r.frac_broken, "#888", 2, [6, 3], chartData.ctrl); legend.push(["control broken", "#888"]); }
    if (S.broken) { line((r) => r.frac_broken, dark ? "#fff" : "#111", 3); legend.push(["broken", dark ? "#fff" : "#111"]); }
    if (S.fit && chartData.fit.s50 != null && chartData.fit.slope && chartData.nDesc > 1) { const { s50, slope: k } = chartData.fit; ctx.beginPath(); ctx.setLineDash([2, 2]); ctx.strokeStyle = "#eb6834"; ctx.lineWidth = 2; for (let i = 0; i < 60; i++) { const x = 1 + (chartData.nDesc - 1) * i / 59, y = Y(1 / (1 + Math.exp(-k * (x - s50)))); i ? ctx.lineTo(X(x), y) : ctx.moveTo(X(x), y); } ctx.stroke(); ctx.setLineDash([]); legend.push([`descent logistic s50=${s50}`, "#eb6834"]); }
    if (S.canary) { ctx.fillStyle = "#eda100"; for (const [t, d] of Object.entries(chartData.canary)) { const x = t - chartData.offset; if (x >= lo && x <= hi && d.context != null) { ctx.beginPath(); ctx.arc(X(x), Y(d.context), 4, 0, 7); ctx.fill(); } } legend.push(["canary (context)", "#eda100"]); }
    let row = 0; ctx.fillStyle = dark ? "#fff" : "#0b0b0b"; ctx.strokeStyle = dark ? "#fff" : "#0b0b0b"; ctx.lineWidth = 1;
    for (const key of ["s_tone", "s_break", "s_capitulate", "s_hostile", "s_refuse", "s_collapse"]) { const s = chartData.eps[key]; if (s == null || s < lo || s > chartData.nDesc) continue; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(X(s), T); ctx.lineTo(X(s), H - B); ctx.stroke(); ctx.setLineDash([]); ctx.fillText(key.replace("s_", ""), X(s) + 3, T + 10 + row++ * 11); }
    let x = L; const y = H - 12; for (const [label, col] of legend) { ctx.fillStyle = col; ctx.fillRect(x, y - 8, 9, 9); ctx.fillStyle = dark ? "#c3c2b7" : "#52514e"; ctx.fillText(label, x + 13, y); x += 13 + ctx.measureText(label).width + 14; if (x > W - 80) break; }
  }

  // ---- compare -----------------------------------------------------------------------------------
  let cmpRows = [], cmpSel = new Set();
  async function fillCompare() {
    cmpRows = await api("/compare"); cmpSel.clear();
    const profs = await api("/profiles");
    $("prof_table").querySelector("tbody").innerHTML = profs.flatMap((pf) => ["narcissist", "psychopath", "machiavellian", "machiavellian_bundle"].filter((p) => p !== "machiavellian_bundle" || (pf.triangle[p] || {}).run_id).map((persona) => { const e = pf.triangle[persona] || {}; const s50 = e.run_id == null ? "no run" : e.censored ? "censored" : fmt(e.s50); const ctrl = (e.control || {}).difference; return `<tr><td>${esc(pf.subject)}</td><td>${persona}</td><td>${s50}</td><td>${fmt(e.density, 3)}</td><td>${e.mode || "-"}</td><td>${fmt(e.scarring, 3)}</td><td>${fmt(ctrl)}</td></tr>`; })).join("");
    $("cmp_table").querySelector("tbody").innerHTML = cmpRows.map((r, i) => `<tr data-i="${i}"><td>${r.run_id}</td><td>${esc(r.run_name)}</td><td>${esc(r.subject)}</td><td>${esc(r.persona)}</td><td>${esc(r.adversary)}</td><td>${r.ladder}/${r.kind}</td><td>${r.status}</td><td>${r.censored ? "censored" : fmt(r.s50)}</td><td>${fmt(r.density, 4)}</td><td>${r.s_break ?? "-"}</td><td>${r.mode ?? "-"}</td><td>${fmt(r.r50)}</td><td>${fmt(r.scarring, 3)}</td><td>${r.confound}</td><td>${r.publishable}</td></tr>`).join("");
    $("cmp_table").querySelectorAll("tr[data-i]").forEach((tr) => (tr.onclick = () => { const i = +tr.dataset.i; cmpSel.has(i) ? cmpSel.delete(i) : cmpSel.add(i); tr.classList.toggle("sel", cmpSel.has(i)); }));
  }
  $("cmp_refresh").onclick = fillCompare;
  $("cmp_diff").onclick = async () => { if (cmpSel.size !== 2) { $("cmp_msg").textContent = "select exactly two rows: a hostile run and its control"; return; } let [a, b] = [...cmpSel].map((i) => cmpRows[i]); if (a.kind === "control" && b.kind !== "control") [a, b] = [b, a]; const d = await api(`/diff?hostile=${a.run_id}&control=${b.run_id}`); $("cmp_msg").textContent = `s50 hostile=${d.s50_hostile} control=${d.s50_control} difference=${d.difference} | scarring hostile=${d.scarring_hostile} control=${d.scarring_control} difference=${d.scarring_difference} (${d.note})`; };

  // ---- label ---------------------------------------------------------------------------------------
  // Two modes (Dhiraj, 2026-10-01). Review: every verdict is shown, items where Claude's blind label and the
  // classifier disagree are red and come first; tick "agree" or choose your own label. Blind: nothing is shown
  // until the label is saved. Final label per sample: review, else blind human, else Claude.
  $("l_radios").innerHTML = ["none", ...MODES].map((m) => `<label><input type="radio" name="lab" value="${m}"> ${m}</label>`).join("");
  try { $("l_by").value = localStorage.getItem("ap_by") || ""; } catch (e) { /* storage blocked */ }
  $("l_by").onchange = () => { try { localStorage.setItem("ap_by", $("l_by").value); } catch (e) { /* ignore */ } };
  const lmode = () => (document.querySelector("input[name=lmode]:checked") || {}).value || "review";
  document.querySelectorAll("input[name=lmode]").forEach((x) => (x.onchange = () => { state.band = []; drawBand(); }));
  function markLabelTab(n) { const b = document.querySelector('button[data-tab="label"]'); if (!b) return; b.textContent = n ? `Label (${n})` : "Label"; b.style.color = n ? "#c0392b" : ""; b.style.fontWeight = n ? "700" : ""; }
  async function refreshReviewCount() { if (!state.run) return markLabelTab(0); try { const rv = await api(`/runs/${state.run}/review?n=40`); markLabelTab(rv.unreviewed); return rv; } catch (e) { markLabelTab(0); } }
  // The band belongs to ONE run. If the selected run changed (by hand or because a new run started), draw again.
  async function drawBandIfEmpty() { if (!state.band.length || state.band[0].run_id !== state.run) drawBand(); }
  async function drawBand() {
    if (lmode() === "review") {
      const rv = await api(`/runs/${state.run}/review?n=40`); state.band = rv.items; markLabelTab(rv.unreviewed);
      $("l_counts").textContent = rv.claude_labelled ? `${rv.disagreements} disagreement(s), ${rv.unreviewed} not yet reviewed; final labels: ${rv.sources.reviewed} reviewed, ${rv.sources.human} blind human, ${rv.sources.claude} Claude; kappa ${rv.kappa}` : "Claude has not labelled this run yet; nothing to review (use Blind, or ask Claude to label it)";
    } else { state.band = await api(`/runs/${state.run}/band?n=40`); $("l_counts").textContent = ""; }
    state.bandI = 0; showLabelItem();
  }
  function showLabelItem() {
    const review = lmode() === "review"; $("l_agree_row").style.display = review ? "" : "none"; $("l_verdicts").innerHTML = "";
    document.querySelectorAll("input[name=lab]").forEach((x) => (x.checked = false)); $("l_agree").checked = false;
    if (!state.band.length || state.bandI >= state.band.length) { $("l_info").textContent = state.band.length ? "end of the band" : "no samples"; $("l_b").textContent = ""; $("l_a").textContent = ""; return; }
    const r = state.band[state.bandI];
    $("l_info").textContent = `run ${r.run_id}  ${state.bandI + 1}/${state.band.length}  turn ${r.turn_idx} sample ${r.sample_idx} dose ${r.step}`;
    $("l_b").textContent = r.b_text || ""; $("l_a").textContent = r.text || "";
    if (review) {
      const red = r.flag ? ' style="color:#c0392b;font-weight:700"' : "";
      $("l_verdicts").innerHTML = `<span${red}>${r.flag ? "NEEDS ATTENTION: " : ""}classifier: ${r.classifier} &nbsp;|&nbsp; Claude: ${r.claude || "(not labelled)"}</span>` +
        (r.human ? ` &nbsp;|&nbsp; your blind label: ${r.human}` : "") + (r.review ? ` &nbsp;|&nbsp; <b>reviewed: ${r.review}</b> by ${r.review_by || "?"}` : "");
      $("l_agree_txt").textContent = r.claude ? `I agree with Claude's label (${r.claude})` : "Claude has no label here; choose yours below";
      $("l_agree").disabled = !r.claude;
      if (r.review) { const x = document.querySelector(`input[name=lab][value="${r.review}"]`); if (x) x.checked = true; $("l_agree").checked = r.review === r.claude; if ($("l_agree").checked && x) x.checked = false; }
    }
  }
  $("l_agree").onchange = () => { if ($("l_agree").checked) document.querySelectorAll("input[name=lab]").forEach((x) => (x.checked = false)); };
  document.querySelectorAll("input[name=lab]").forEach((x) => (x.onchange = () => { $("l_agree").checked = false; }));
  $("l_draw").onclick = drawBand; $("l_skip").onclick = () => { state.bandI++; showLabelItem(); };
  $("l_save").onclick = async () => {
    if (!state.band.length || state.bandI >= state.band.length) return; const r = state.band[state.bandI];
    if (r.run_id !== state.run) { $("l_kappa").textContent = "the selected run changed; drawing its own band"; await drawBand(); return; }
    const review = lmode() === "review"; const picked = document.querySelector("input[name=lab]:checked");
    const label = review && $("l_agree").checked ? r.claude : (picked ? picked.value : null);
    if (!label) { $("l_kappa").textContent = review ? "tick 'agree' or choose a label" : "choose a label"; return; }
    let labeller = "human";
    if (review) { const by = ($("l_by").value || "").trim(); if (!by) { $("l_kappa").textContent = "enter your name in the reviewer box first"; return; } labeller = `review:${by}`; }
    const out = await api(`/runs/${r.run_id}/labels`, { method: "POST", body: JSON.stringify({ turn_idx: r.turn_idx, sample_idx: r.sample_idx, label, labeller }) });
    if (review) { r.review = label; r.review_by = labeller.slice(7); $("l_kappa").textContent = `saved: ${label}  |  labels=${out.n_labels} kappa=${out.kappa}`; refreshReviewCount(); }
    else { $("l_kappa").textContent = `saved: you=${label}, classifier=${r.lexical_mode || "none"}  |  labels=${out.n_labels} kappa vs lexical=${out.kappa}`; }
    state.bandI++; showLabelItem();
  };

  // ---- report ---------------------------------------------------------------------------------------
  async function fillReport(full = false) { const rep = await api(`/runs/${state.run}/report?ci=${$("r_ci").checked}&examples=${$("r_examples").checked}&full=${!!full}`); $("r_text").textContent = rep.text; $("r_banner").innerHTML = `<div class="banner ${rep.validity.publishable ? "ok" : "bad"}"><b>VALIDITY GATE: ${rep.validity.publishable ? "PUBLISHABLE" : "NOT PUBLISHABLE — " + rep.validity.blocking.join(", ")}</b> &nbsp; persona ${rep.persona}, dose ${rep.dose_semantics}</div>`; }
  $("r_refresh").onclick = () => fillReport(false); $("r_examples").onchange = () => fillReport(false); $("r_full").onclick = () => fillReport(true);
  $("r_recompute").onclick = async () => { const r = await api(`/runs/${state.run}/metrics`, { method: "POST" }); $("r_text").textContent += `\nrecomputed ${r.recomputed} samples`; fillReport(); };

  // ---- settings ---------------------------------------------------------------------------------------
  async function fillSettings() { const cs = await api("/credentials"); $("k_form").innerHTML = cs.map((c) => `<div class="row"><label style="width:260px">${c.provider}  (${c.env})</label><input type="password" data-env="${c.env}" placeholder="${c.masked || "not set"}" class="grow"></div>`).join(""); }
  $("k_save").onclick = async () => { const body = {}; $("k_form").querySelectorAll("input").forEach((i) => { if (i.value) body[i.dataset.env] = i.value; }); await api("/credentials", { method: "POST", body: JSON.stringify(body) }); $("k_msg").textContent = `${Object.keys(body).length} credential(s) updated`; fillSettings(); initForm(); };
  $("j_run").onclick = async () => { $("j_msg").textContent = "judging..."; try { const r = await api(`/runs/${state.run}/judge`, { method: "POST", body: JSON.stringify({ kind: $("j_kind").value, model: $("j_model").value, n: +$("j_n").value }) }); $("j_msg").textContent = `judge ${r.judge || ""}: kappa vs lexical = ${r.kappa} on n=${r.n} ${r.note || ""}`; } catch (e) { $("j_msg").textContent = "judge failed: " + e.message; } };

  // ---- approval --------------------------------------------------------------------------------------
  try { $("ap_by").value = localStorage.getItem("ap_by") || ""; } catch (e) { /* storage blocked */ }
  $("ap_by").onchange = () => { try { localStorage.setItem("ap_by", $("ap_by").value); } catch (e) { /* ignore */ } };
  const markPivot = (t) => esc(t).replace(/\[([^\]]+)\]/g, '<span class="pv">$1</span>');
  let apState = null;
  async function fillApproval() {
    const lads = await api("/approvals");
    const cur = $("ap_ladder").value;
    $("ap_ladder").innerHTML = lads.map((l) => `<option value="${l.ladder_id}">${l.ladder_id}  ${l.persona}  ${l.status}  ${l.approved}/${l.total} approved${l.change_requests ? `, ${l.change_requests} change request(s)` : ""}${l.stale ? `, ${l.stale} changed since approval` : ""}</option>`).join("");
    if (cur && lads.some((l) => l.ladder_id === cur)) $("ap_ladder").value = cur;
    await showApproval();
  }
  async function showApproval() {
    const lid = $("ap_ladder").value; if (!lid) return;
    apState = await api(`/approvals/${lid}`);
    const s = apState;
    $("ap_summary").className = "banner " + (s.status === "frozen" && s.frozen_current ? "ok" : "bad");
    $("ap_summary").innerHTML = `<b>${s.ladder_id}</b> (${s.persona}) is <b>${s.status}</b>. ${s.approved} of ${s.total} lines approved` + (s.change_requests ? `, ${s.change_requests} change request(s)` : "") + (s.stale ? `, ${s.stale} line(s) changed since approval` : "") + (s.frozen ? `. Last frozen ${esc(s.frozen.at)} by ${esc(s.frozen.by || "?")}, hash ${esc(String(s.frozen.sha256).slice(0, 16))}${s.frozen_current ? "" : " (content has changed since)"}` : "") + ".";
    $("ap_freeze").disabled = !s.can_freeze || (s.status === "frozen" && s.frozen_current);
    const onlyOpen = $("ap_open").checked;
    let html = "", sec = "";
    s.lines.forEach((ln, i) => {
      if (onlyOpen && ln.approved) return;
      if (ln.section !== sec) { sec = ln.section; html += `<div class="apsec">${esc(sec)}</div>`; }
      const cls = ln.approved ? "done" : ln.stale ? "stale" : ln.comment ? "req" : "";
      html += `<div class="apcard ${cls}" data-i="${i}"><h4>${esc(ln.label)}${ln.stale ? " (text changed since approval)" : ""}</h4>`
        + ln.fields.map(([k, v]) => `<div class="apfield"><span class="k">${esc(k)}</span><span>${markPivot(v)}</span></div>`).join("")
        + `<div class="row"><label><input type="checkbox" class="ap_ok" ${ln.approved ? "checked" : ""}> approve</label>`
        + `<span class="muted">${ln.by ? "by " + esc(ln.by) + " " : ""}${ln.at ? esc(ln.at) : ""}</span></div>`
        + `<textarea class="ap_c" placeholder="change request or note (leave the line unticked to request a change)">${esc(ln.comment || "")}</textarea></div>`;
    });
    $("ap_lines").innerHTML = html || '<p class="muted">Every line is approved.</p>';
    $("ap_lines").querySelectorAll(".apcard").forEach((card) => {
      const ln = s.lines[+card.dataset.i];
      const save = async () => {
        await api(`/approvals/${s.ladder_id}`, { method: "POST", body: JSON.stringify({ key: ln.key, approved: card.querySelector(".ap_ok").checked, comment: card.querySelector(".ap_c").value, by: $("ap_by").value }) });
        await fillApproval();
      };
      card.querySelector(".ap_ok").onchange = save;
      card.querySelector(".ap_c").onchange = save;
    });
  }
  $("ap_ladder").onchange = showApproval;
  $("ap_open").onchange = showApproval;
  $("ap_freeze").onclick = async () => {
    if (!apState) return;
    const r = await api(`/approvals/${apState.ladder_id}/freeze`, { method: "POST", body: JSON.stringify({ by: $("ap_by").value }) });
    alert(r.ok ? `Frozen. Identity hash ${String(r.sha256).slice(0, 16)}.` : `Not frozen: ${r.reason}`);
    await fillApproval();
  };

  // ---- boot ------------------------------------------------------------------------------------------
  (async () => { await initForm(); await fillSettings(); await refreshRuns(); await refreshQuota(); await refreshLlama(); await fillAbout(); setInterval(refreshQuota, 30000); setInterval(refreshLlama, 60000); showTab("run"); })();
})();
