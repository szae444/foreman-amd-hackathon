// Foreman control room — vanilla JS, no build step.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 1) => (n == null || Number.isNaN(n) ? "—" : Number(n).toFixed(d));

const S = {
  parts: [],
  incidents: new Map(),
  selectedPart: null, // pinned part id, or null = follow live
  pinUntil: 0,
  selectedIncident: null,
  followIncidents: true,
  line: null,
  sensors: null,
  detMs: null,
  lastDiag: null,
  reasonStart: {}, // "<id>:<trigger>" -> ms timestamp, from this browser's clock
};

// Live elapsed time while Gemma reasons, so a long diagnosis reads as work, not a hang.
setInterval(() => {
  for (const el of document.querySelectorAll("[data-elapsed]")) {
    const inc = S.incidents.get(Number(el.dataset.elapsed));
    const t0 = inc && S.reasonStart[`${inc.id}:${inc.trigger}`];
    if (t0) el.textContent = `${Math.floor((Date.now() - t0) / 1000)} s`;
  }
}, 250);

const FAULT_SIG = {
  die_wear: "vibration ↑  → scratches",
  transfer_misalign: "ram force ↑ → bent parts",
  lube_degradation: "die temp ↑ lube ↓ → discoloration",
  feeder_orientation: "misfeeds ↑ → flipped parts",
};
const DEFECT_LABEL = { scratch: "Scratch", bent: "Bent / deformed", color: "Discoloration", flip: "Flipped part", other: "Other defect", none: "No defect" };

// ───────────────────────── theme
(function theme() {
  let saved = null;
  try { saved = localStorage.getItem("foreman-theme"); } catch {}
  if (saved) document.documentElement.dataset.theme = saved;
  $("themeToggle").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("foreman-theme", next); } catch {}
  });
})();

setInterval(() => { $("clock").textContent = new Date().toLocaleTimeString([], { hour12: false }); }, 1000);

// ───────────────────────── API
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}
const post = (path, body = {}) => api(path, { method: "POST", body: JSON.stringify(body) });

// ───────────────────────── viewer
const stage = $("viewerStage");
$("reveal").addEventListener("input", (e) => stage.style.setProperty("--reveal", `${e.target.value}%`));
stage.style.setProperty("--reveal", "50%");

function showPart(p) {
  if (!p) return;
  $("viewerEmpty").hidden = true;
  $("viewImage").src = p.image;
  $("viewHeat").src = p.heatmap;
  $("viewer").dataset.flag = p.flagged ? "flagged" : "good";
  $("partId").textContent = p.id;
  const v = $("partVerdict");
  v.textContent = p.flagged ? "Flagged" : "Good";
  v.dataset.v = p.flagged ? "flagged" : "good";
  $("partScore").textContent = fmt(p.score, 2);
  $("partThresh").textContent = fmt(p.threshold, 2);
  const ratio = Math.min(p.score / p.threshold / 1.5, 1);
  $("scoreFill").style.width = `${ratio * 100}%`;
  let region = p.flagged ? `${p.region}` : "within the distribution of good parts";
  if (p.suppressed) region += " · repair in progress, no new incident";
  $("partRegion").textContent = `${region} · ${fmt(p.latency_ms, 0)} ms`;
  const bb = $("bbox");
  if (p.flagged && p.bbox) {
    const [x0, y0, x1, y1] = p.bbox;
    const s = p.size || 224;
    Object.assign(bb.style, { left: `${(x0 / s) * 100}%`, top: `${(y0 / s) * 100}%`, width: `${((x1 - x0) / s) * 100}%`, height: `${((y1 - y0) / s) * 100}%` });
    bb.hidden = false;
  } else bb.hidden = true;
  S.detMs = p.latency_ms;
  $("mDet").textContent = `${fmt(p.latency_ms, 0)} ms / part`;
  renderFilmstrip();
}

function renderFilmstrip() {
  const shown = S.parts.slice(0, 16);
  const current = S.selectedPart || shown[0]?.id;
  $("filmstrip").innerHTML = shown
    .map((p) => `<li data-id="${esc(p.id)}" data-flag="${p.flagged ? 1 : 0}" data-sel="${p.id === current ? 1 : 0}" title="${esc(p.id)} · ${fmt(p.score, 2)}"><img src="${p.image}" alt="" loading="lazy"></li>`)
    .join("");
}
$("filmstrip").addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (!li) return;
  const p = S.parts.find((x) => x.id === li.dataset.id);
  S.selectedPart = p.id;
  S.pinUntil = Date.now() + 12000;
  showPart(p);
});

function onPart(p) {
  S.parts.unshift(p);
  S.parts = S.parts.slice(0, 30);
  if (!S.selectedPart || Date.now() > S.pinUntil || p.trigger === "upload") {
    S.selectedPart = null;
    showPart(p);
  } else renderFilmstrip();
}

// ───────────────────────── sensors
function sparkline(series, r) {
  const W = 240, H = 36;
  if (!series?.length) return "";
  const lo = Math.min(...series, r.alarm_lo), hi = Math.max(...series, r.alarm_hi);
  const pad = (hi - lo) * 0.08 || 1;
  const y = (v) => H - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * H;
  const x = (i) => (i / (series.length - 1)) * W;
  const d = series.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <rect class="band" x="0" width="${W}" y="${y(r.warn_hi)}" height="${Math.max(0, y(r.warn_lo) - y(r.warn_hi))}"/>
    <rect class="band-alarm" x="0" width="${W}" y="${y(r.alarm_hi)}" height="${Math.max(0, y(r.alarm_lo) - y(r.alarm_hi))}"/>
    <line class="base" x1="0" x2="${W}" y1="${y(r.baseline)}" y2="${y(r.baseline)}"/>
    <path class="line" d="${d}"/></svg>`;
}

function renderSensors(s) {
  if (!s) return;
  S.sensors = s;
  const chip = $("sensorStatus");
  chip.dataset.state = s.status;
  chip.textContent = { ok: "Normal", warn: "Watch", alarm: "Alarm" }[s.status];
  $("sensors").innerHTML = s.readings
    .map((r) => {
      const z = `${r.z >= 0 ? "+" : ""}${fmt(r.z, 1)}σ`;
      const digits = Math.abs(r.baseline) < 10 ? 2 : 1;
      return `<li class="sensor" data-state="${r.status}">
        <span class="sensor-name">${esc(r.label)}</span>
        <span class="sensor-val"><span class="v">${fmt(r.value, digits)}</span><span class="u">${esc(r.unit)}</span><span class="z">${z}</span></span>
        ${sparkline(s.history?.[r.key], r)}
      </li>`;
    })
    .join("");
}

// ───────────────────────── line controls
function renderLine(line) {
  if (!line) return;
  S.line = line;
  $("btnRun").textContent = line.running ? "Pause line" : "Start line";
  $("btnRun").classList.toggle("btn-ink", !line.running);
  const lamp = $("lineLamp");
  lamp.dataset.state = line.fault ? "fault" : line.running ? "running" : "idle";
  $("lineStatus").textContent = line.running ? (line.fault ? "Running · fault" : "Running") : "Idle";
  $("faultState").textContent = line.fault
    ? `${line.fault.label} · ${Math.round(line.fault.severity * 100)}%${line.repair_scheduled ? " · repair underway" : ""}`
    : "No fault injected";
  $("cInspected").textContent = line.counters.inspected;
  $("cFlagged").textContent = line.counters.flagged;
  const box = $("faults");
  if (!box.children.length) {
    for (const f of line.faults) {
      const el = $("tplFault").content.firstElementChild.cloneNode(true);
      el.dataset.key = f.key;
      el.querySelector(".fault-name").textContent = f.label;
      el.querySelector(".fault-sig").textContent = FAULT_SIG[f.key] || f.defect_type;
      el.addEventListener("click", () => act(() => post("/api/line/inject", { fault: f.key })));
      box.appendChild(el);
    }
  }
  for (const el of box.children) el.dataset.active = line.fault?.key === el.dataset.key ? 1 : 0;
}

async function act(fn) {
  try { const r = await fn(); if (r?.faults) renderLine(r); } catch (e) { banner(e.message, "error"); }
}
$("btnRun").addEventListener("click", () => act(() => post(S.line?.running ? "/api/line/stop" : "/api/line/start")));
$("btnStep").addEventListener("click", () => act(() => post("/api/line/step")));
$("btnClear").addEventListener("click", () => act(() => post("/api/line/clear")));

// ───────────────────────── incidents
function onIncident(inc) {
  if (!inc) return;
  S.incidents.set(inc.id, inc);
  if (S.followIncidents || S.selectedIncident === inc.id || S.selectedIncident == null) {
    if (S.followIncidents) S.selectedIncident = inc.id;
  }
  if (inc.llm?.latency_ms) showLastDiag(inc.llm);
  renderLog();
  renderTicket();
}

function showLastDiag(llm) {
  S.lastDiag = llm;
  $("mDiag").textContent = `${(llm.latency_ms / 1000).toFixed(1)} s · ${llm.completion_tokens || 0} tok`;
}

function renderLog() {
  const list = [...S.incidents.values()].sort((a, b) => b.id - a.id).slice(0, 12);
  const open = list.filter((i) => i.status === "pending_review" || i.status === "reasoning").length;
  $("incCount").textContent = `${S.incidents.size} incidents · ${open} open`;
  $("log").innerHTML = list
    .map((i) => {
      const d = i.diagnosis || {};
      const title = d.probable_cause || (i.status === "reasoning" ? "Gemma is reasoning…" : i.error || "—");
      return `<li data-id="${i.id}" data-sel="${i.id === S.selectedIncident ? 1 : 0}">
        <span class="id">#${String(i.id).padStart(3, "0")}</span>
        <span>${esc(title)}${i.linked_parts ? ` <span class="linked">+${i.linked_parts} parts</span>` : ""}</span>
        <span class="st" data-s="${i.status}">${esc(i.status.replace("_", " "))}</span></li>`;
    })
    .join("");
}
$("log").addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (!li) return;
  S.selectedIncident = Number(li.dataset.id);
  const latest = Math.max(...S.incidents.keys());
  S.followIncidents = S.selectedIncident === latest;
  renderLog();
  renderTicket();
});

function classify(text) {
  const t = text.toLowerCase().trim();
  // The prompt asks for "Camera: …", "Sensor: …", "Manual §x.y: …" prefixes; fall back to keywords.
  if (/^(camera|detector|vision|heatmap)\b/.test(t)) return "camera";
  if (/^sensors?\b/.test(t)) return "sensor";
  if (/^manual\b/.test(t)) return "manual";
  if (/§|manual|p\.\d/.test(t)) return "manual";
  if (/sensor|vibration|force|temp|pressure|misfeed|σ|kn\b|bar\b|mm\/s/.test(t)) return "sensor";
  return "camera";
}

function renderTicket() {
  const t = $("ticket"), body = $("ticketBody");
  const inc = S.incidents.get(S.selectedIncident);
  if (!inc) { t.dataset.state = "empty"; body.innerHTML = ""; return; }
  t.dataset.state = inc.status;
  const det = inc.detection || {};
  const when = new Date(inc.created_at * 1000).toLocaleTimeString([], { hour12: false });
  const trig = { vision: "Camera", sensor: "Sensors", upload: "Upload", escalated: "Sensors → camera" }[inc.trigger] || inc.trigger;
  const meta = `<div class="t-meta"><span>Incident <b>#${String(inc.id).padStart(3, "0")}</b></span><span>${when}</span><span>Trigger <b>${esc(trig)}</b></span><span>Part <b>${esc(inc.part_id || "—")}</b></span>${inc.linked_parts ? `<span><b>+${inc.linked_parts}</b> linked parts</span>` : ""}</div>`;

  if (inc.status === "reasoning") {
    const n = (inc.sections || []).length;
    const key = `${inc.id}:${inc.trigger}`; // escalation restarts the clock
    if (!S.reasonStart[key]) S.reasonStart[key] = Date.now();
    body.innerHTML = `<div class="t-head">${meta}</div><div class="thinking">
      <span class="big">Reasoning</span>
      <ol class="stages">
        <li data-s="done"><span>Detect — PatchCore score ×${fmt(det.severity, 2)}, ${esc(det.region || "")}</span></li>
        <li data-s="done"><span>Fuse — sensors: ${esc(inc.sensors?.status || "ok")}</span></li>
        <li data-s="done"><span>Retrieve — ${n} manual sections</span></li>
        <li data-s="run"><span>Reason — Gemma 4 · photo + heatmap + ${n} sections · <b class="mono" data-elapsed="${inc.id}">0 s</b></span></li>
        <li><span>Draft work order → supervisor</span></li>
      </ol></div>`;
    return;
  }
  if (inc.status === "error") {
    body.innerHTML = `<div class="t-head">${meta}<h3 class="t-cause">Reasoning failed</h3><p class="t-desc mono">${esc(inc.error)}</p></div>`;
    return;
  }

  const d = inc.diagnosis || {};
  const wo = d.work_order || {};
  const conf = Math.round((d.cause_confidence ?? 0) * 100);
  const cites = inc.llm?.citations || {};
  const verified = new Set(cites.verified || []);
  const refs = (d.manual_refs || []).map((r) => `<span class="ref" data-ok="${verified.has(r) ? 1 : 0}">${esc(r)}</span>`).join("");
  const items = (d.evidence || []).map((e) => ({ src: classify(e), text: e, auto: false }));
  if (inc.sensors?.status !== "ok" && !items.some((i) => i.src === "sensor")) {
    // The model left the machine out of its evidence: Foreman adds the abnormal readings itself, labelled.
    for (const line of (inc.sensors?.summary || "").split("\n").filter(Boolean)) items.push({ src: "sensor", text: line, auto: true });
  }
  const evidence = items.map((i) => `<li><span class="src" data-s="${i.src}">${i.src}</span><span>${esc(i.text)}${i.auto ? ' <em class="auto">added by Foreman, not in the model’s evidence</em>' : ""}</span></li>`).join("");
  const cons = inc.llm?.consistency;
  const conflict = cons && !cons.agrees
    ? `<div class="conflict" role="alert"><b>Camera and sensors disagree.</b> The sensor pattern matches ${esc(cons.via)} → <b>${esc(DEFECT_LABEL[cons.sensors_suggest] || cons.sensors_suggest)}</b>, but the model reads <b>${esc(DEFECT_LABEL[cons.model_says] || cons.model_says)}</b>. Check the part before approving.</div>`
    : cons?.agrees ? `<div class="agree">Camera and sensors agree: ${esc(cons.via)} → ${esc(DEFECT_LABEL[cons.sensors_suggest] || cons.sensors_suggest)}.</div>` : "";
  const act = inc.llm?.action_check;
  const actionNote = act && !act.ok
    ? `<div class="conflict" role="note"><b>The manual allows the press to keep running.</b> ${esc(act.ref)}: “${esc(act.quote)}” The model recommends stopping the line; the supervisor decides.</div>`
    : "";
  const steps = (wo.steps || []).map((s) => `<li>${esc(s)}</li>`).join("");
  const alts = (d.alternative_causes || []).map((a) => `<li><b>${esc(a.cause)}</b> — ${esc(a.why_less_likely)}</li>`).join("");
  const contain = (d.containment || []).map((s) => `<li>${esc(s)}</li>`).join("");
  const stamp = inc.status === "approved"
    ? `<div class="stamp" data-s="approved">Approved<small>${esc(inc.work_order_no || "")} · ${esc(inc.reviewer || "")}</small></div>`
    : inc.status === "rejected" ? `<div class="stamp" data-s="rejected">Rejected<small>${esc(inc.reviewer || "")}</small></div>` : "";
  const actions = inc.status === "pending_review"
    ? `<div class="actions"><input id="reviewNote" placeholder="Note for the record (optional)" />
        <button class="btn" id="btnReject">Reject</button>
        <button class="btn btn-accent" id="btnApprove">Approve work order</button></div>`
    : inc.review_note ? `<div class="t-section"><h4>Supervisor note</h4><p class="t-desc">${esc(inc.review_note)}</p></div>` : "";
  const llm = inc.llm || {};

  body.innerHTML = `
    <div class="t-head">${meta}${stamp}
      <h3 class="t-cause">${esc(d.probable_cause || DEFECT_LABEL[d.defect_type] || "—")}</h3>
      <p class="t-desc">${esc(d.visual_description || "")}</p>
      <div class="pills">
        <span class="pill">${esc(DEFECT_LABEL[d.defect_type] || d.defect_type || "?")}</span>
        <span class="pill" data-k="${esc(d.severity)}">${esc(d.severity || "")}</span>
        <span class="pill" data-k="${esc(d.recommended_action)}">${esc((d.recommended_action || "").replaceAll("_", " "))}</span>
        <span class="pill">${esc(d.verdict || "")}</span>
      </div>
      ${conflict}${actionNote}
    </div>
    <div class="perf"></div>
    <div class="t-section"><h4>Confidence in cause</h4>
      <div class="confidence" data-low="${conf < 60 ? 1 : 0}"><span class="pct">${conf}%</span><span class="track"><b style="width:${conf}%"></b></span><span class="mono muted small">${conf < 60 ? "low — verify" : "calibrated by model"}</span></div>
    </div>
    <div class="t-section"><h4>Evidence</h4><ul class="evidence">${evidence}</ul></div>
    ${alts ? `<div class="t-section"><h4>Ruled less likely</h4><ul class="alts">${alts}</ul></div>` : ""}
    <div class="t-section"><h4>Work order · ${esc(wo.priority || "")} · ${esc(wo.title || "")}</h4>
      <ol class="steps">${steps}</ol>
      <dl class="kv">
        <div><dt>Est. downtime</dt><dd class="mono">${wo.est_downtime_min ?? "—"} min</dd></div>
        <div><dt>Parts</dt><dd>${esc((wo.parts || []).join(", ") || "—")}</dd></div>
        <div><dt>Tools</dt><dd>${esc((wo.tools || []).join(", ") || "—")}</dd></div>
      </dl>
      ${(wo.safety || []).length ? `<p class="t-desc small"><b>Safety:</b> ${esc(wo.safety.join(" · "))}</p>` : ""}
    </div>
    ${contain ? `<div class="t-section"><h4>Containment</h4><ol class="steps">${contain}</ol></div>` : ""}
    <div class="t-section"><h4>Manual citations</h4><div class="refs-list">${refs || '<span class="muted">none</span>'}</div></div>
    <div class="t-section operator"><h4>Operator message</h4>
      <blockquote lang="en">${esc(d.operator_message_en || "")}</blockquote>
      <blockquote lang="it">${esc(d.operator_message_it || "")}</blockquote>
    </div>
    ${actions}
    <p class="llm-foot">${esc(llm.model || "")} · ${llm.mode === "mock" ? "MOCK — not a real model output" : "live model output"} ·${fmt((llm.latency_ms || 0) / 1000, 1)} s · ${llm.prompt_tokens || 0} prompt / ${llm.completion_tokens || 0} completion tokens${llm.tokens_per_s ? ` · ${llm.tokens_per_s} tok/s` : ""}</p>`;

  if (inc.status === "pending_review") {
    const note = () => $("reviewNote").value;
    $("btnApprove").addEventListener("click", () => review(inc.id, true, note()));
    $("btnReject").addEventListener("click", () => review(inc.id, false, note()));
  }
}

async function review(id, approve, note) {
  try {
    const inc = await post(`/api/incidents/${id}/${approve ? "approve" : "reject"}`, { reviewer: "Shift supervisor", note });
    onIncident(inc);
  } catch (e) { banner(e.message, "error"); }
}

// ───────────────────────── ask
$("askForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("askInput").value.trim();
  if (!q) return;
  const box = $("answer");
  box.hidden = false;
  box.textContent = "Reading the manual…";
  try {
    const r = await post("/api/ask", { question: q, incident_id: S.selectedIncident });
    box.innerHTML = `${esc(r.answer)}<span class="refs">${r.sections.map((s) => esc(`${s.ref} ${s.title}`)).join(" · ")} — ${esc(r.llm.model)} · ${fmt(r.llm.latency_ms / 1000, 1)} s</span>`;
  } catch (err) { box.textContent = `Error: ${err.message}`; }
});

// ───────────────────────── upload
const dz = $("dropzone");
async function upload(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  dz.querySelector(".mono").textContent = "Inspecting…";
  try {
    const res = await fetch("/api/inspect", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    S.followIncidents = true;
  } catch (e) { banner(e.message, "error"); }
  dz.querySelector(".mono").textContent = "Inspect your own image";
}
$("uploadInput").addEventListener("change", (e) => upload(e.target.files[0]));
for (const ev of ["dragenter", "dragover"]) dz.addEventListener(ev, (e) => { e.preventDefault(); dz.dataset.over = 1; });
for (const ev of ["dragleave", "drop"]) dz.addEventListener(ev, (e) => { e.preventDefault(); dz.dataset.over = 0; });
dz.addEventListener("drop", (e) => upload(e.dataTransfer.files[0]));
stage.addEventListener("dragover", (e) => e.preventDefault());
stage.addEventListener("drop", (e) => { e.preventDefault(); upload(e.dataTransfer.files[0]); });

// ───────────────────────── telemetry
function renderTelemetry(t) {
  if (!t) return;
  const g = t.gpu || {}, v = t.vllm || {};
  // Name only what is actually detected: never imply AMD hardware that isn't there.
  const cpu = g.kind === "cpu";
  $("gpuName").textContent = g.name ? String(g.name) : g.source === "pending" ? "Detecting hardware…" : "No GPU telemetry";
  $("gpuSource").textContent = cpu ? `CPU only · ${g.cores ?? "?"} threads · no GPU used`
    : g.source === "none" || !g.source ? "no GPU telemetry on this host" : `${g.source}${g.gpus > 1 ? ` · ${g.gpus} GPUs` : ""}`;
  $("lUtil").textContent = cpu ? "CPU util" : "GPU util";
  $("lVram").textContent = cpu ? "RAM" : "VRAM";
  $("mUtil").textContent = g.util_pct != null ? `${fmt(g.util_pct, 0)}%` : "—";
  $("bUtil").style.width = `${g.util_pct || 0}%`;
  $("mVram").textContent = g.vram_used_gb != null ? `${fmt(g.vram_used_gb, 0)} / ${fmt(g.vram_total_gb, 0)} GB` : g.vram_pct != null ? `${fmt(g.vram_pct, 0)}%` : "—";
  $("bVram").style.width = `${g.vram_pct || 0}%`;
  $("mPower").textContent = g.power_w != null ? `${fmt(g.power_w, 0)} W` : "—";
  $("mTemp").textContent = g.temp_c != null ? `${fmt(g.temp_c, 0)} °C` : "—";
  $("mTps").textContent = v.ok ? (v.gen_tokens_per_s ? `${fmt(v.gen_tokens_per_s, 0)} tok/s` : "idle") : S.lastDiag?.tokens_per_s ? `${S.lastDiag.tokens_per_s} tok/s` : "—";
  $("mKv").textContent = v.ok && v.kv_cache_pct != null ? `${fmt(v.kv_cache_pct, 1)}%` : "—";
}

function renderHealth(state) {
  const llm = state.llm || {};
  const badge = $("modeBadge");
  if (llm.mode === "mock") { badge.dataset.mode = "mock"; badge.textContent = "Mock LLM"; }
  else if (!llm.ok) { badge.dataset.mode = "down"; badge.textContent = "LLM offline"; }
  else { badge.dataset.mode = "live"; badge.textContent = (llm.model || "").split("/").pop(); }
  const det = state.detector || {};
  const m = det.meta || {};
  $("detMeta").textContent = det.ready ? `PatchCore · AUROC ${m.image_auroc ?? "—"} · ${m.runtime_device || ""}` : "detector not loaded";
  $("manualMeta").textContent = state.manual ? `${state.manual.sections} sections indexed` : "—";
  const msgs = [];
  if (!det.ready) msgs.push(det.error || "Detector not loaded.");
  if (llm.mode === "mock") msgs.push("MOCK MODE — diagnoses are placeholders. Set FOREMAN_LLM_MODE=live and point FOREMAN_LLM_BASE_URL at vLLM before recording a demo.");
  else if (!llm.ok) msgs.push(`Gemma endpoint unreachable: ${llm.error || ""}`);
  if (msgs.length) banner(msgs.join("  ·  "), det.ready ? "warn" : "error");
  else if (state.notice) banner(state.notice, "info");
  else $("banner").hidden = true;
}

function banner(text, level = "warn") {
  const b = $("banner");
  b.textContent = text;
  b.dataset.level = level;
  b.hidden = false;
}

// ───────────────────────── boot
async function boot() {
  const st = await api("/api/state");
  renderHealth(st);
  renderLine(st.line);
  renderSensors(st.sensors);
  renderTelemetry(st.telemetry);
  S.parts = st.parts || [];
  if (S.parts[0]) showPart(S.parts[0]);
  for (const inc of [...(st.incidents || [])].reverse()) S.incidents.set(inc.id, inc);
  const lastLlm = (st.incidents || []).find((i) => i.llm?.latency_ms)?.llm;
  if (lastLlm) showLastDiag(lastLlm);
  const open = (st.incidents || []).find((i) => i.status === "pending_review" || i.status === "reasoning");
  S.selectedIncident = open?.id ?? st.incidents?.[0]?.id ?? null;
  renderLog();
  renderTicket();

  const es = new EventSource("/api/events");
  es.addEventListener("part", (e) => onPart(JSON.parse(e.data)));
  es.addEventListener("sensors", (e) => renderSensors(JSON.parse(e.data)));
  es.addEventListener("line", (e) => renderLine(JSON.parse(e.data)));
  es.addEventListener("incident", (e) => onIncident(JSON.parse(e.data)));
  es.addEventListener("telemetry", (e) => renderTelemetry(JSON.parse(e.data)));
  setInterval(async () => { try { renderHealth(await api("/api/health").then((h) => ({ ...st, llm: h.llm, detector: { ...st.detector, ready: h.detector } }))); } catch {} }, 30000);
}
boot().catch((e) => banner(`Cannot reach Foreman API: ${e.message}`, "error"));
