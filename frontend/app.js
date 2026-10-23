// Market Analyser chart. Read-only: it loads candles and analysis, and never sends orders.
(() => {
  const HL_WS = "wss://api.hyperliquid.xyz/ws";
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  // one colour per kind of annotation; the same colours appear as swatches in the Layers panel
  const C = {
    text: dark ? "#ececea" : "#1d1d1b",
    muted: dark ? "#8b8b86" : "#787b86",
    grid: dark ? "#25262b" : "#f0f0ec",
    bull: "#089981",
    bear: "#f23645",
    fvgBull: "rgba(8,153,129,0.14)",
    fvgBear: "rgba(242,54,69,0.14)",
    obBull: "#2962ff",
    obBear: "#ff6d00",
    obBullFill: "rgba(41,98,255,0.14)",
    obBearFill: "rgba(255,109,0,0.14)",
    liq: "#f5b700",
    vwap: "#9c27b0",
    premium: "rgba(242,54,69,0.045)",
    discount: "rgba(8,153,129,0.045)",
    ote: "#00a3bf",
    oteFill: "rgba(0,163,191,0.06)",
    kz: dark ? "rgba(255,255,255,0.035)" : "rgba(0,0,0,0.03)",
    profile: dark ? "rgba(148,163,184,0.3)" : "rgba(120,123,134,0.22)",
    poc: dark ? "rgba(148,163,184,0.7)" : "rgba(120,123,134,0.6)",
    entry: "#2962ff",
    stop: "#f23645",
    target: "#089981",
  };


  const el = (id) => document.getElementById(id);
  const chartEl = el("chart");
  const overlay = el("overlay");
  const ctx = overlay.getContext("2d");

  const chart = LightweightCharts.createChart(chartEl, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: C.muted, attributionLogo: true },
    grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
    timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 14 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  const candles = chart.addCandlestickSeries({
    upColor: C.bull, downColor: C.bear, borderVisible: false, wickUpColor: C.bull, wickDownColor: C.bear,
  });
  const volume = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

  const RECENT = 150; // candles back for markers and zones, so the chart stays readable
  const MAX_ZONES = 8;

  let state = { coin: "BTC", interval: "15m", report: null, demo: false };
  let ws = null;
  let lastBarTime = null;
  let refreshTimer = null;

  const layerOn = (name) => document.querySelector(`[data-layer="${name}"]`).checked;
  const sec = (ms) => Math.floor(ms / 1000);
  const fmt = (x) => x == null ? "–" : Number(x).toLocaleString(undefined, { maximumFractionDigits: x < 10 ? 4 : 2 });

  function setStatus(text, error = false) {
    el("status").textContent = text;
    el("status").className = error ? "error" : "";
  }

  async function load() {
    state.coin = el("coin").value.trim() || "BTC";
    state.interval = el("interval").value;
    setStatus("Loading…");
    try {
      const res = await fetch(`/api/analysis?coin=${encodeURIComponent(state.coin)}&interval=${state.interval}&limit=500`);
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      state.report = await res.json();
    } catch (err) {
      setStatus(`Could not load ${state.coin}: ${err.message}`, true);
      return;
    }
    render(true);
    connectLive();
    setStatus(state.demo ? "Demo data (offline)" : `Live · ${state.coin} ${state.interval}`);
  }

  function render(fit) {
    const r = state.report;
    candles.setData(r.candles.map((k) => ({ time: sec(k.t), open: k.o, high: k.h, low: k.l, close: k.c })));
    volume.setData(r.candles.map((k) => ({
      time: sec(k.t), value: k.v, color: k.c >= k.o ? "rgba(8,153,129,0.3)" : "rgba(242,54,69,0.3)",
    })));
    lastBarTime = r.candles.at(-1).t;

    const markers = [];
    if (layerOn("sweeps")) {
      const since = r.candles.at(-RECENT).t;
      for (const s of r.sweeps.filter((s) => s.time >= since)) {
        const bull = s.direction === "bullish";
        markers.push({
          time: sec(s.time), position: bull ? "belowBar" : "aboveBar", color: bull ? C.bull : C.bear,
          shape: bull ? "arrowUp" : "arrowDown", size: 0.8,
        });
      }
    }
    markers.sort((a, b) => a.time - b.time);
    candles.setMarkers(markers);

    // start zoomed on the most recent candles, where the annotations matter
    if (fit) chart.timeScale().setVisibleLogicalRange({ from: r.candles.length - RECENT, to: r.candles.length + 14 });
    renderSummary(r);
    renderSetups(r);
    renderEvents(r);
  }

  function short(source) {
    return { swing: "", "equal highs": "EQH", "equal lows": "EQL" }[source] ?? source;
  }

  function utcDay(ms) {
    return Math.floor(ms / 86_400_000);
  }

  function renderSummary(r) {
    const dr = r.dealing_range;
    el("s-price").textContent = fmt(r.last.price);
    el("s-trend").innerHTML = r.trend ? `<span class="${r.trend === "bullish" ? "bull" : "bear"}">${r.trend}</span>` : "no break yet";
    el("s-zone").textContent = dr ? `${dr.zone} (${Math.round(dr.position * 100)}%)${dr.in_ote ? " · in OTE" : ""}` : "–";
    el("s-htf").textContent = r.htf_interval ? `${r.htf_trend ?? "no break yet"} (${r.htf_interval})` : "–";
    el("s-kz").textContent = r.last.killzone ?? "outside killzones";
    el("s-atr").textContent = fmt(r.last.atr);
    el("s-rvol").textContent = r.last.rvol == null ? "–" : `${r.last.rvol.toFixed(2)}x`;
  }

  const lastStatus = {};

  function renderSetups(r) {
    el("setups").innerHTML = r.setups.map((s) => {
      const checks = s.checks.map((c) => {
        const mark = c.status === "pass" ? "✓" : c.status === "fail" ? "✗" : "–";
        return `<li><span class="mark-${c.status === "pass" ? "pass" : "fail"}">${mark}</span>${c.label}<small>${c.detail}</small></li>`;
      }).join("");
      const plan = s.entry != null && s.stop != null
        ? `<div class="plan">Entry ${fmt(s.entry)} · Stop ${fmt(s.stop)} · Targets ${s.targets.map(fmt).join(", ") || "–"}${s.reward_risk != null ? ` · ${s.reward_risk}R` : ""}</div>`
        : "";
      return `<div class="setup"><div class="setup-head"><span class="${s.direction === "long" ? "bull" : "bear"}">${s.direction === "long" ? "Long" : "Short"} ${s.score}/${s.max_score}</span><span class="badge ${s.status}">${s.status === "none" ? "no setup" : s.status}</span></div><ul class="checks">${checks}</ul>${plan}</div>`;
    }).join("");

    // alert when a setup newly becomes ready for the market on screen
    const key = `${r.coin}:${r.interval}`;
    for (const s of r.setups) {
      const id = `${key}:${s.direction}`;
      if (s.status === "ready" && lastStatus[id] && lastStatus[id] !== "ready") notify(`${r.coin} ${r.interval}: ${s.direction} setup ready at ${fmt(s.entry)}`);
      lastStatus[id] = s.status;
    }
  }

  function notify(text) {
    const box = el("alert");
    box.textContent = text;
    box.hidden = false;
    if ("Notification" in window && Notification.permission === "granted") new Notification("Market Analyser", { body: text });
  }

  function renderEvents(r) {
    const items = [
      ...r.structure.map((e) => ({ t: e.time, dir: e.direction, text: `${e.type} ${e.direction} at ${fmt(e.level)}${e.displacement ? " with displacement" : ""}` })),
      ...r.sweeps.map((s) => ({ t: s.time, dir: s.direction, text: `Swept ${s.source} ${fmt(s.level)}` })),
      ...r.order_blocks.map((b) => ({ t: r.candles[b.event_index].t, dir: b.direction, text: `New ${b.direction} order block ${fmt(b.bottom)} to ${fmt(b.top)}` })),
    ].sort((a, b) => b.t - a.t).slice(0, 20);
    el("events").innerHTML = items.map((i) => {
      const when = new Date(i.t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      return `<li><span class="${i.dir === "bullish" ? "bull" : "bear"}">●</span> ${i.text} <small>${when}</small></li>`;
    }).join("");
  }

  // ---- overlay drawing (zones, levels, ranges) ----
  // Shapes are drawn on the chart; all level labels go in the empty strip right of the last candle
  // as coloured tags, so no text sits on top of the candles.

  function resizeOverlay() {
    const dpr = window.devicePixelRatio || 1;
    const { width, height } = chartEl.getBoundingClientRect();
    overlay.width = width * dpr;
    overlay.height = height * dpr;
    overlay.style.width = `${width}px`;
    overlay.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function x(ms) {
    return ms == null ? null : chart.timeScale().timeToCoordinate(sec(ms));
  }
  function y(price) {
    return candles.priceToCoordinate(price);
  }
  function plotRight() {
    return chartEl.clientWidth - chart.priceScale("right").width();
  }
  function plotBottom() {
    return chartEl.clientHeight - chart.timeScale().height();
  }

  let tags = [];

  // queue a label for the right-hand strip; lower priority numbers win when labels collide
  function tag(price, text, bg, priority, fg = "#ffffff") {
    const yy = y(price);
    if (yy != null && yy > 0 && yy < plotBottom()) tags.push({ y: yy, text, bg, fg, priority });
  }

  function pill(px, py, text, bg, fg, align = "left") {
    ctx.font = "600 11px system-ui, sans-serif";
    const w = ctx.measureText(text).width + 10, h = 16;
    const left = align === "right" ? px - w : align === "center" ? px - w / 2 : px;
    ctx.fillStyle = bg;
    ctx.beginPath();
    ctx.roundRect(left, py - h / 2, w, h, 4);
    ctx.fill();
    ctx.fillStyle = fg;
    ctx.textBaseline = "middle";
    ctx.fillText(text, left + 5, py + 0.5);
    ctx.textBaseline = "alphabetic";
    return w;
  }

  function drawTags() {
    // place the most important labels first; each may slide up to MAX_SHIFT px off its price
    // to avoid another label, and is dropped if it can't, so no label ends up far from its level
    const H = 17, MAX_SHIFT = 22;
    const placed = [];
    const free = (yy) => placed.every((p) => Math.abs(p.at - yy) >= H);
    for (const t of [...tags].sort((a, b) => a.priority - b.priority)) {
      for (let d = 0; d <= MAX_SHIFT; d++) {
        const yy = free(t.y - d) ? t.y - d : free(t.y + d) ? t.y + d : null;
        if (yy != null) { placed.push({ ...t, at: yy }); break; }
      }
    }
    const right = plotRight() - 4;
    for (const t of placed) {
      ctx.font = "600 11px system-ui, sans-serif";
      const w = ctx.measureText(t.text).width + 10;
      if (Math.abs(t.at - t.y) > 2) {
        ctx.strokeStyle = t.bg;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(right - w - 8, t.y);
        ctx.lineTo(right - w, t.at);
        ctx.stroke();
      }
      pill(right, t.at, t.text, t.bg, t.fg, "right");
    }
  }

  function rect(t0, t1, top, bottom, fill, stroke, dashed) {
    const right = plotRight();
    let x0 = x(t0);
    let x1 = t1 == null ? right : x(t1);
    if (x0 == null) x0 = 0;
    if (x1 == null) x1 = right;
    const y0 = y(top), y1 = y(bottom);
    if (y0 == null || y1 == null) return;
    ctx.fillStyle = fill;
    ctx.fillRect(x0, y0, Math.max(1, Math.min(x1, right) - x0), y1 - y0);
    if (stroke) {
      ctx.setLineDash(dashed ? [4, 3] : []);
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1;
      ctx.strokeRect(x0 + 0.5, y0 + 0.5, Math.min(x1, right) - x0, y1 - y0);
      ctx.setLineDash([]);
    }
  }

  function hline(t0, t1, price, color, dash, width = 1) {
    const right = plotRight();
    const x0 = x(t0) ?? 0;
    const x1 = t1 == null ? right : (x(t1) ?? right);
    const yy = y(price);
    if (yy == null) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(dash);
    ctx.beginPath();
    ctx.moveTo(x0, Math.round(yy) + 0.5);
    ctx.lineTo(Math.min(x1, right), Math.round(yy) + 0.5);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function draw() {
    const w = chartEl.clientWidth, h = chartEl.clientHeight;
    ctx.clearRect(0, 0, w, h);
    const r = state.report;
    if (!r) return;
    tags = [];
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, plotRight(), plotBottom());
    ctx.clip();

    const atr = r.last.atr;
    const price = r.last.price;
    const showDead = layerOn("filled");
    const since = r.candles.at(-RECENT).t;

    if (layerOn("killzones")) {
      for (const k of r.killzones) {
        const x0 = x(k.start_time), x1 = x(k.end_time);
        if (x0 == null || x1 == null) continue;
        ctx.fillStyle = C.kz;
        ctx.fillRect(x0, 0, Math.max(2, x1 - x0), plotBottom());
      }
    }

    const vp = r.volume_profile;
    if (layerOn("profile") && vp) {
      // on the left edge, away from the labels on the right
      const maxV = Math.max(...vp.bins.map((b) => b.volume));
      for (const b of vp.bins) {
        const y0 = y(b.high), y1 = y(b.low);
        if (y0 == null || y1 == null) continue;
        const isPoc = vp.poc >= b.low && vp.poc <= b.high;
        ctx.fillStyle = isPoc ? C.poc : C.profile;
        ctx.fillRect(0, y0, (b.volume / maxV) * 110, Math.max(1, y1 - y0 - 1));
      }
      hline(null, null, vp.vah, C.muted, [2, 2]);
      hline(null, null, vp.val, C.muted, [2, 2]);
      tag(vp.vah, "VAH", C.muted, 5);
      tag(vp.val, "VAL", C.muted, 5);
    }

    const dr = r.dealing_range;
    if (layerOn("range") && dr) {
      rect(dr.start_time, null, dr.high, dr.equilibrium, C.premium);
      rect(dr.start_time, null, dr.equilibrium, dr.low, C.discount);
      hline(dr.start_time, null, dr.equilibrium, C.muted, [2, 3]);
      rect(dr.start_time, null, dr.ote_high, dr.ote_low, C.oteFill, C.ote, true);
      tag(dr.equilibrium, "EQ 50%", C.muted, 4);
      tag((dr.ote_high + dr.ote_low) / 2, "OTE", C.ote, 3);
    }

    if (layerOn("fvg")) {
      const live = (g) => g.status === "open" || g.status === "partial";
      const gaps = r.fvgs.filter((g) => showDead || live(g)).slice(-MAX_ZONES);
      for (const g of gaps) {
        const bull = g.direction === "bullish";
        rect(g.time, live(g) ? null : g.filled_time, g.top, g.bottom, bull ? C.fvgBull : C.fvgBear);
      }
    }

    if (layerOn("ob")) {
      const blocks = r.order_blocks.filter((b) => showDead || b.status !== "breaker").slice(-MAX_ZONES);
      for (const b of blocks) {
        const breaker = b.status === "breaker";
        const bull = b.direction === "bullish";
        rect(b.time, breaker ? b.end_time : null, b.top, b.bottom, bull ? C.obBullFill : C.obBearFill, bull ? C.obBull : C.obBear, breaker);
      }
    }

    if (layerOn("vwap")) {
      drawVwap(r.vwap);
      tag(r.vwap.at(-1).vwap, "VWAP", C.vwap, 3);
    }

    if (layerOn("liquidity")) {
      for (const lv of r.liquidity) {
        if (lv.swept_at != null || Math.abs(lv.price - price) > 6 * atr) continue;
        hline(lv.time, null, lv.price, C.liq, [2, 3]);
        const label = lv.source === "swing" ? (lv.kind === "buy-side" ? "BSL" : "SSL") : short(lv.source);
        tag(lv.price, label, C.liq, lv.source === "swing" ? 6 : 2, "#1d1d1b");
      }
    }

    if (layerOn("structure")) {
      const boxes = [];
      for (const e of r.structure.filter((e) => e.time >= since).slice(-8).reverse()) {
        const bull = e.direction === "bullish";
        const color = bull ? C.bull : C.bear;
        hline(e.swing_time, e.time, e.level, color, e.type === "CHoCH" ? [5, 3] : [], 1.5);
        const x1 = x(e.time), yy = y(e.level);
        if (x1 == null || yy == null) continue;
        // tag at the break candle, just off the line; skipped if it would cover a newer tag
        const py = bull ? yy - 11 : yy + 11;
        ctx.font = "600 11px system-ui, sans-serif";
        const bw = ctx.measureText(e.type).width + 10;
        if (boxes.some((b) => x1 + 4 < b.x + b.w && b.x < x1 + 4 + bw && Math.abs(b.y - py) < 17)) continue;
        boxes.push({ x: x1 + 4, y: py, w: bw });
        pill(x1 + 4, py, e.type, color, "#ffffff");
      }
    }

    if (layerOn("plan")) {
      for (const s of r.setups) {
        if (s.status === "none" || s.entry == null) continue;
        const long = s.direction === "long";
        rect(s.zone_time, null, s.zone_top, s.zone_bottom, "rgba(0,0,0,0)", C.entry, true);
        hline(s.zone_time, null, s.entry, C.entry, [], 2);
        hline(s.sweep_time, null, s.stop, C.stop, [6, 3], 1.5);
        tag(s.entry, `${long ? "Long" : "Short"} entry`, C.entry, 0);
        tag(s.stop, "Stop", C.stop, 0);
        s.targets.forEach((tp, i) => {
          hline(s.zone_time, null, tp, C.target, [6, 3], 1.5);
          tag(tp, `Target ${i + 1}`, C.target, 1);
        });
      }
    }

    ctx.restore();
    drawTags();
  }

  // drawn by hand so the line breaks where VWAP resets each UTC day
  function drawVwap(points) {
    ctx.strokeStyle = C.vwap;
    for (const [m, width, dash] of [[0, 2, []], [1, 1, [3, 3]], [-1, 1, [3, 3]], [2, 1, [1, 3]], [-2, 1, [1, 3]]]) {
      ctx.lineWidth = width;
      ctx.globalAlpha = m === 0 ? 1 : 0.55;
      ctx.setLineDash(dash);
      ctx.beginPath();
      let prev = null;
      for (const p of points) {
        const px = x(p.t), py = y(p.vwap + m * p.sd);
        if (px == null || py == null) { prev = null; continue; }
        if (prev && utcDay(prev.t) === utcDay(p.t)) ctx.lineTo(px, py);
        else ctx.moveTo(px, py);
        prev = p;
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
  }

  function loop() {
    draw();
    requestAnimationFrame(loop);
  }

  // ---- live updates straight from Hyperliquid ----

  function connectLive() {
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    if (state.demo) return;
    const sub = { type: "candle", coin: state.coin, interval: state.interval };
    ws = new WebSocket(HL_WS);
    ws.onopen = () => ws.send(JSON.stringify({ method: "subscribe", subscription: sub }));
    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.channel !== "candle") return;
      const k = data.data;
      if (k.s !== state.coin || k.i !== state.interval) return;
      const t = Number(k.t);
      candles.update({ time: sec(t), open: +k.o, high: +k.h, low: +k.l, close: +k.c });
      volume.update({ time: sec(t), value: +k.v, color: +k.c >= +k.o ? "rgba(8,153,129,0.3)" : "rgba(242,54,69,0.3)" });
      el("s-price").textContent = fmt(+k.c);
      if (lastBarTime != null && t > lastBarTime) {
        // the previous candle just closed: re-run the detectors on closed data
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(refresh, 1500);
      }
      lastBarTime = Math.max(lastBarTime ?? 0, t);
    };
    ws.onclose = () => { setTimeout(() => { if (!ws || ws.readyState === WebSocket.CLOSED) connectLive(); }, 3000); };
  }

  async function refresh() {
    try {
      const res = await fetch(`/api/analysis?coin=${encodeURIComponent(state.coin)}&interval=${state.interval}&limit=500`);
      if (res.ok) { state.report = await res.json(); render(false); }
    } catch { /* keep the last good report */ }
  }

  // ---- wiring ----

  // colour swatches next to each layer toggle, taken from the palette above
  const swatch = {
    structure: [C.bull, C.bear], fvg: [C.fvgBull, C.fvgBear], ob: [C.obBull, C.obBear], liquidity: [C.liq],
    sweeps: [C.bull, C.bear], range: [C.ote], killzones: [C.muted], vwap: [C.vwap], profile: [C.muted],
    plan: [C.entry, C.stop, C.target],
  };
  for (const [layer, colors] of Object.entries(swatch)) {
    const label = document.querySelector(`[data-layer="${layer}"]`).parentElement;
    const sw = document.createElement("span");
    sw.className = "swatch";
    sw.style.background = colors.length > 1 ? `linear-gradient(90deg, ${colors.join(", ")})` : colors[0];
    label.append(sw);
  }

  el("controls").addEventListener("submit", (e) => {
    e.preventDefault();
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    load();
  });
  el("interval").addEventListener("change", load);
  document.querySelectorAll("[data-layer]").forEach((box) => box.addEventListener("change", () => state.report && render(false)));
  new ResizeObserver(resizeOverlay).observe(chartEl);
  resizeOverlay();
  requestAnimationFrame(loop);

  fetch("/api/config").then((r) => r.json()).then((cfg) => { state.demo = cfg.demo; load(); });
})();
