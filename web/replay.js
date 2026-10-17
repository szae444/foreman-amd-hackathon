// Foreman replay: plays back one recorded live run (PatchCore + Gemma 4 on an AMD Ryzen CPU) in the
// real UI, for the static demo page. Nothing is computed here: every event and response is what the
// running app sent during the recording (scripts/record_replay.py). The visitor's clicks move the
// recording forward at the same points where the recorder acted.
(() => {
  const REC = "./replay/recording.json";
  const LIVE_ONLY = "This page replays one recorded run, so this needs the live app. Run it yourself: github.com/szae444/foreman-amd-hackathon";
  const realNow = Date.now.bind(Date);
  const base = realNow();
  let rec = null, r = 0, last = performance.now(), shift = 0, sent = 0, gate = 0, ff = null;
  const sources = [];
  const ready = fetch(REC).then((x) => x.json()).then((x) => {
    rec = x;
    shift = base / 1000 - rec.recorded_at;
    const m = rec.marks || {};
    if (m.escalated != null && m.ready != null) ff = { a: m.escalated + 10, b: m.ready - 1, real: m.ready - m.escalated };
    requestAnimationFrame(tick);
  });

  // recorded epoch seconds -> now, so times of day and ages read as fresh
  const fresh = (o) => {
    if (Array.isArray(o)) return o.map(fresh);
    if (o && typeof o === "object") return Object.fromEntries(Object.entries(o).map(([k, v]) => [k, fresh(v)]));
    if (typeof o === "number" && o > 1.6e9 && o < 2.3e9) return o + shift;
    return o;
  };
  // the UI's own clocks (reasoning timer, part pinning) follow the recording, not the wall
  Date.now = () => base + r * 1000;

  const gates = () => (rec ? rec.actions.filter((a) => a.gate) : []);
  const nextGate = () => gates()[gate] || null;
  const speed = () => (ff && r >= ff.a && r < ff.b ? (ff.b - ff.a) / 20 : 1);

  function tick(now) {
    const dt = Math.min(0.25, (now - last) / 1000);
    last = now;
    const g = nextGate();
    const limit = g ? g.t : Infinity;
    r = Math.min(limit, r + dt * speed());
    while (sent < rec.events.length && rec.events[sent].t <= r) {
      const e = rec.events[sent++];
      const data = JSON.stringify(fresh(e.data));
      for (const s of sources) for (const f of s.l[e.event] || []) f({ data });
    }
    guide(g, r >= limit);
    requestAnimationFrame(tick);
  }

  // ── a fake EventSource the app subscribes to
  window.EventSource = class {
    constructor() { this.l = {}; sources.push(this); }
    addEventListener(n, f) { (this.l[n] ||= []).push(f); }
    close() {}
  };

  // ── API: recorded responses, gated on the visitor's clicks
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const lastLine = () => {
    for (let i = sent - 1; i >= 0; i--) if (rec.events[i].event === "line") return fresh(rec.events[i].data);
    return fresh(rec.state.line);
  };
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, opts = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (!url.startsWith("/api/")) return realFetch(input, opts);
    await ready;
    const path = url.split("?")[0], method = (opts.method || "GET").toUpperCase();
    if (method === "GET" && path === "/api/state") {
      return json({ ...fresh(rec.state), notice: "Replay of a recorded live run: PatchCore + Gemma 4 E2B on an AMD Ryzen 7 7435HS, CPU only. Nothing runs in your browser; your clicks step through the recording." });
    }
    if (method === "GET" && path === "/api/health") return json(fresh(rec.health));
    if (method === "GET" && path.startsWith("/api/incidents/")) {
      const id = Number(path.split("/").pop());
      for (let i = sent - 1; i >= 0; i--) { const e = rec.events[i]; if (e.event === "incident" && e.data.id === id) return json(fresh(e.data)); }
      return json({ detail: "not found" }, 404);
    }
    if (path === "/api/ask" || path === "/api/inspect" || path.endsWith("/reject") || path === "/api/line/step" || path === "/api/line/clear") {
      return json({ detail: LIVE_ONLY }, 409);
    }
    const g = nextGate();
    if (g && matches(g, path, opts)) {
      r = Math.max(r, g.t); // an early but correct click jumps ahead to it
      gate++;
      return json(fresh(g.response));
    }
    hint(g);
    return json(lastLine());
  };
  function matches(g, path, opts) {
    if (g.kind === "inject") {
      let body = {};
      try { body = JSON.parse(opts.body || "{}"); } catch {}
      return path === "/api/line/inject" && body.fault === g.body.fault;
    }
    if (g.kind === "approve") return path.endsWith("/approve");
    return path === g.path;
  }

  // ── the guide: what the next click is, and when the recording is fast-forwarded
  const NEXT = { start: "press START LINE", inject: "inject the fault “Lubricant degradation”", approve: "approve the work order" };
  let pill = null, hintUntil = 0;
  function el() {
    if (pill) return pill;
    pill = document.createElement("div");
    pill.style.cssText = "position:fixed;left:50%;bottom:104px;transform:translateX(-50%);z-index:50;background:#16140f;color:#efebe2;" +
      "font:600 13px/1.3 'IBM Plex Mono',monospace;letter-spacing:.06em;padding:10px 16px;border:2px solid #ff5a1f;max-width:calc(100vw - 32px);text-align:center";
    document.body.appendChild(pill);
    return pill;
  }
  function hint(g) {
    hintUntil = performance.now() + 4000;
    const p = el();
    p.textContent = g ? `In this recorded run, the next step is: ${NEXT[g.kind] || g.kind}.` : "The recording has ended. Reload the page to replay it.";
  }
  function guide(g, waiting) {
    if (!document.body || performance.now() < hintUntil) return;
    const p = el();
    const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
    if (ff && r >= ff.a && r < ff.b) p.textContent = `FAST-FORWARD ×${Math.round(speed())} · camera-confirmed diagnosis took ${fmt(ff.real)} on the Ryzen CPU in this recording`;
    else if (g && waiting) p.textContent = `RECORDED RUN · Next: ${NEXT[g.kind] || g.kind}`;
    else if (!g && sent >= (rec?.events.length || 0)) p.textContent = "RECORDED RUN · End of the recording. Reload to replay.";
    else p.textContent = "RECORDED RUN · playing";
  }
})();
