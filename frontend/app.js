// Market Analyser chart. Read-only: it loads candles and analysis, and never sends orders.
(() => {
  const HL_WS = "wss://api.hyperliquid.xyz/ws";
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const C = {
    text: dark ? "#ececea" : "#1d1d1b",
    muted: dark ? "#9a9a95" : "#6b6b66",
    grid: dark ? "#25262b" : "#efeeea",
    bull: "#16a34a",
    bear: "#dc2626",
    fvgBull: "rgba(22,163,74,0.16)",
    fvgBear: "rgba(220,38,38,0.16)",
    obBull: "rgba(37,99,235,0.18)",
    obBear: "rgba(234,88,12,0.18)",
    liq: dark ? "#fbbf24" : "#b45309",
    vwap: dark ? "#a78bfa" : "#7c3aed",
    premium: "rgba(220,38,38,0.05)",
    discount: "rgba(22,163,74,0.05)",
    ote: dark ? "rgba(96,165,250,0.6)" : "rgba(37,99,235,0.6)",
    kz: dark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.035)",
    profile: dark ? "rgba(148,163,184,0.35)" : "rgba(100,116,139,0.28)",
  };

  const el = (id) => document.getElementById(id);
  const chartEl = el("chart");
  const overlay = el("overlay");
  const ctx = overlay.getContext("2d");

  const chart = LightweightCharts.createChart(chartEl, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: C.muted, attributionLogo: true },
    grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
    timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 8 },
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
      time: sec(k.t), value: k.v, color: k.c >= k.o ? "rgba(22,163,74,0.35)" : "rgba(220,38,38,0.35)",
    })));
    lastBarTime = r.candles.at(-1).t;

    const markers = [];
    if (layerOn("sweeps")) {
      const since = r.candles.at(-RECENT).t;
      for (const s of r.sweeps.filter((s) => s.time >= since)) {
        const bull = s.direction === "bullish";
        markers.push({
          time: sec(s.time), position: bull ? "belowBar" : "aboveBar", color: bull ? C.bull : C.bear,
          shape: bull ? "arrowUp" : "arrowDown", text: short(s.source),
        });
      }
    }
    markers.sort((a, b) => a.time - b.time);
    candles.setMarkers(markers);

    if (fit) chart.timeScale().fitContent();
    renderSummary(r);
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
    el("s-kz").textContent = r.last.killzone ?? "outside killzones";
    el("s-atr").textContent = fmt(r.last.atr);
    el("s-rvol").textContent = r.last.rvol == null ? "–" : `${r.last.rvol.toFixed(2)}x`;
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

  function hline(t0, t1, price, color, dash, label) {
    const right = plotRight();
    let x0 = x(t0) ?? 0;
    let x1 = t1 == null ? right : (x(t1) ?? right);
    const yy = y(price);
    if (yy == null) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash(dash);
    ctx.beginPath();
    ctx.moveTo(x0, yy + 0.5);
    ctx.lineTo(Math.min(x1, right), yy + 0.5);
    ctx.stroke();
    ctx.setLineDash([]);
    if (label) {
      ctx.fillStyle = color;
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillText(label, Math.min(x1, right) - ctx.measureText(label).width - 4, yy - 3);
    }
  }

  function draw() {
    const w = chartEl.clientWidth, h = chartEl.clientHeight;
    ctx.clearRect(0, 0, w, h);
    const r = state.report;
    if (!r) return;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, plotRight(), plotBottom());
    ctx.clip();

    const atr = r.last.atr;
    const price = r.last.price;
    const showDead = layerOn("filled");

    if (layerOn("killzones")) {
      for (const k of r.killzones) {
        const x0 = x(k.start_time), x1 = x(k.end_time);
        if (x0 == null || x1 == null) continue;
        ctx.fillStyle = C.kz;
        ctx.fillRect(x0, 0, Math.max(2, x1 - x0), plotBottom());
        ctx.fillStyle = C.muted;
        ctx.font = "10px system-ui, sans-serif";
        if (ctx.measureText(k.name).width + 4 < x1 - x0) ctx.fillText(k.name, x0 + 2, 12);
      }
    }

    const dr = r.dealing_range;
    if (layerOn("range") && dr) {
      rect(dr.start_time, null, dr.high, dr.equilibrium, C.premium);
      rect(dr.start_time, null, dr.equilibrium, dr.low, C.discount);
      hline(dr.start_time, null, dr.equilibrium, C.muted, [2, 3], "EQ 50%");
      rect(dr.start_time, null, dr.ote_high, dr.ote_low, "rgba(0,0,0,0)", C.ote, true);
      ctx.fillStyle = C.ote;
      ctx.font = "11px system-ui, sans-serif";
      const yy = y(dr.ote_high);
      if (yy != null) ctx.fillText("OTE", (x(dr.start_time) ?? 0) + 4, yy + 12);
    }

    if (layerOn("fvg")) {
      const live = (g) => g.status === "open" || g.status === "partial";
      const gaps = r.fvgs.filter((g) => showDead || live(g)).slice(-MAX_ZONES);
      for (const g of gaps) {
        const dead = !live(g);
        rect(g.time, dead ? g.filled_time : null, g.top, g.bottom, g.direction === "bullish" ? C.fvgBull : C.fvgBear);
      }
    }

    if (layerOn("ob")) {
      const blocks = r.order_blocks.filter((b) => showDead || b.status !== "breaker").slice(-MAX_ZONES);
      for (const b of blocks) {
        const breaker = b.status === "breaker";
        const bull = b.direction === "bullish";
        rect(b.time, breaker ? b.end_time : null, b.top, b.bottom, bull ? C.obBull : C.obBear, bull ? "#2563eb" : "#ea580c", breaker);
      }
    }

    if (layerOn("vwap")) drawVwap(r.vwap);

    if (layerOn("liquidity")) {
      for (const lv of r.liquidity) {
        if (lv.swept_at != null) continue;
        if (Math.abs(lv.price - price) > 6 * atr) continue;
        const label = lv.source === "swing" ? (lv.kind === "buy-side" ? "BSL" : "SSL") : short(lv.source);
        hline(lv.time, null, lv.price, C.liq, [1, 3], label);
      }
    }

    if (layerOn("structure")) {
      for (const e of r.structure.slice(-14)) {
        const color = e.direction === "bullish" ? C.bull : C.bear;
        hline(e.swing_time, e.time, e.level, color, e.type === "CHoCH" ? [5, 3] : [], "");
        const x0 = x(e.swing_time), x1 = x(e.time), yy = y(e.level);
        if (x0 == null || x1 == null || yy == null) continue;
        ctx.fillStyle = color;
        ctx.font = "600 10px system-ui, sans-serif";
        const label = e.type;
        ctx.fillText(label, (x0 + x1) / 2 - ctx.measureText(label).width / 2, e.direction === "bullish" ? yy - 4 : yy + 12);
      }
    }

    ctx.restore();

    const vp = r.volume_profile;
    if (layerOn("profile") && vp) {
      const maxV = Math.max(...vp.bins.map((b) => b.volume));
      const right = plotRight();
      for (const b of vp.bins) {
        const y0 = y(b.high), y1 = y(b.low);
        if (y0 == null || y1 == null) continue;
        const width = (b.volume / maxV) * 120;
        const isPoc = vp.poc >= b.low && vp.poc <= b.high;
        ctx.fillStyle = isPoc ? C.vwap : C.profile;
        ctx.fillRect(right - width, y0, width, Math.max(1, y1 - y0 - 1));
      }
      hline(null, null, vp.vah, C.muted, [2, 2], "VAH");
      hline(null, null, vp.val, C.muted, [2, 2], "VAL");
    }
  }

  // drawn by hand so the line breaks where VWAP resets each UTC day
  function drawVwap(points) {
    ctx.strokeStyle = C.vwap;
    for (const [m, width, dash] of [[0, 2, []], [1, 1, [3, 3]], [-1, 1, [3, 3]], [2, 1, [1, 3]], [-2, 1, [1, 3]]]) {
      ctx.lineWidth = width;
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
      volume.update({ time: sec(t), value: +k.v, color: +k.c >= +k.o ? "rgba(22,163,74,0.35)" : "rgba(220,38,38,0.35)" });
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

  el("controls").addEventListener("submit", (e) => { e.preventDefault(); load(); });
  el("interval").addEventListener("change", load);
  document.querySelectorAll("[data-layer]").forEach((box) => box.addEventListener("change", () => state.report && render(false)));
  new ResizeObserver(resizeOverlay).observe(chartEl);
  resizeOverlay();
  requestAnimationFrame(loop);

  fetch("/api/config").then((r) => r.json()).then((cfg) => { state.demo = cfg.demo; load(); });
})();
