// Market Analyser chart. Read-only: it loads candles and analysis, and never sends orders.
(() => {
  const HL_WS = "wss://api.hyperliquid.xyz/ws";
  const dark = true; // the page always uses the black and orange theme
  // one colour per kind of annotation; the same colours appear as swatches in the Layers panel
  const C = {
    text: dark ? "#ececea" : "#1d1d1b",
    muted: dark ? "#8b8b86" : "#787b86",
    grid: dark ? "#1d1d20" : "#f0f0ec",
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
    // pre-market and after-hours candles are faded
    extBull: "rgba(8,153,129,0.4)",
    extBear: "rgba(242,54,69,0.4)",
    extLine: "#ff8a00",
    profile: dark ? "rgba(148,163,184,0.3)" : "rgba(120,123,134,0.22)",
    poc: dark ? "rgba(148,163,184,0.7)" : "rgba(120,123,134,0.6)",
    entry: "#2962ff",
    stop: "#f23645",
    target: "#089981",
    labelBg: dark ? "rgba(12,12,13,0.92)" : "rgba(255,255,255,0.92)",
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
  const STRUCTURE_LABELS = 6; // only the latest breaks are labelled

  let state = { coin: "SPY", interval: "15m", report: null, demo: false, context: null, research: false };
  let ws = null;
  let lastBarTime = null;
  let refreshTimer = null;
  let pollTimer = null;
  let extLine = null; // the dashed pre-market / after-hours price line

  const layerOn = (name) => document.querySelector(`[data-layer="${name}"]`).checked;
  const sec = (ms) => Math.floor(ms / 1000);
  const fmt = (x) => x == null ? "–" : Number(x).toLocaleString(undefined, { maximumFractionDigits: x < 10 ? 4 : 2 });

  // pre-market and after-hours: on unless switched off, remembered between visits
  const extBox = el("ext");
  try { extBox.checked = localStorage.getItem("ma-ext") !== "0"; } catch { /* storage blocked: keep the default */ }
  const nyClock = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "numeric", hourCycle: "h23" });
  // same rule as the server: a bar is extended hours unless it opens inside 9:30 to 16:00 New York on a weekday
  function isExtended(ms) {
    const p = Object.fromEntries(nyClock.formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
    const mins = Number(p.hour) * 60 + Number(p.minute);
    return p.weekday === "Sat" || p.weekday === "Sun" || mins < 570 || mins >= 960;
  }
  const extColor = (k) => k.ext ? (k.c >= k.o ? C.extBull : C.extBear) : undefined;

  function setStatus(text, error = false) {
    el("status").textContent = text;
    el("status").className = error ? "error" : "";
  }

  const analysisUrl = () => `/api/analysis?coin=${encodeURIComponent(state.coin)}&interval=${state.interval}&limit=500&ext=${extBox.checked}`;

  let loadSeq = 0; // bumps on every switch, so answers for a market you already left are dropped

  async function load() {
    const seq = ++loadSeq;
    state.coin = el("coin").value.trim() || "SPY";
    state.interval = el("interval").value;
    // stop everything still running for the previous market
    clearTimeout(refreshTimer);
    clearInterval(pollTimer);
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    setStatus(`Loading ${state.coin}…`);
    let report;
    try {
      const res = await fetch(analysisUrl());
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      report = await res.json();
    } catch (err) {
      if (seq === loadSeq) setStatus(`Could not load ${state.coin}: ${err.message}`, true);
      return;
    }
    if (seq !== loadSeq) return;
    state.report = report;
    render(true);
    connectLive();
    const crypto = state.report.asset.kind === "crypto";
    const from = {
      hyperliquid: crypto ? `Live · ${state.report.asset.coin} on Hyperliquid` : `${state.report.asset.coin} perp on Hyperliquid (Yahoo Finance unavailable)`,
      yahoo: crypto ? `${state.report.asset.yahoo} from Yahoo Finance (Hyperliquid unavailable, refreshes every minute)` : `${state.report.asset.yahoo} shares from Yahoo Finance, ${state.report.ext ? "incl. pre and after hours" : "regular hours only"} · refreshes every minute`,
      demo: "Demo data (offline)",
    };
    setStatus(`${from[state.report.source]} · ${state.interval}`);
    markWatchlist();
    await window.Strategy?.market(state.report.asset, true);
    if (seq !== loadSeq) return;
    loadContext();
  }

  function render(fit) {
    const r = state.report;
    candles.setData(r.candles.map((k) => {
      const color = extColor(k);
      return color ? { time: sec(k.t), open: k.o, high: k.h, low: k.l, close: k.c, color, wickColor: color }
        : { time: sec(k.t), open: k.o, high: k.h, low: k.l, close: k.c };
    }));
    volume.setData(r.candles.map((k) => ({
      time: sec(k.t), value: k.v, color: k.c >= k.o ? `rgba(8,153,129,${k.ext ? 0.12 : 0.3})` : `rgba(242,54,69,${k.ext ? 0.12 : 0.3})`,
    })));
    lastBarTime = r.candles.at(-1).t;
    renderExtended(r);

    const markers = [];
    if (layerOn("sweeps")) {
      const since = r.candles[Math.max(0, r.candles.length - RECENT)].t;
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

    if (fit) {
      // a new market or timeframe: undo any drag on the price axis so the candles are in view, and start zoomed
      // on the most recent candles, where the annotations matter
      chart.priceScale("right").applyOptions({ autoScale: true });
      chart.priceScale("vol").applyOptions({ autoScale: true });
      chart.timeScale().setVisibleLogicalRange({ from: r.candles.length - RECENT, to: r.candles.length + 14 });
    }
    renderSummary(r);
    renderSetups(r);
    renderEvents(r);
  }

  // the latest pre-market or after-hours price, as a dashed line across the chart and a line under Price
  function renderExtended(r) {
    if (extLine) { candles.removePriceLine(extLine); extLine = null; }
    const stock = r.asset.kind !== "crypto";
    extBox.disabled = !stock;
    extBox.parentElement.title = stock ? "Show pre-market and after-hours trading on the chart" : "Crypto trades round the clock, so it has no pre-market";
    el("ext-note").hidden = !r.ext;
    const x = r.extended;
    el("s-ext-row").hidden = el("s-ext").hidden = !x;
    if (!x) return;
    const change = x.change_pct == null ? "" : ` (${x.change_pct >= 0 ? "+" : ""}${x.change_pct.toFixed(2)}%)`;
    const at = new Date(x.t).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    el("s-ext-row").textContent = x.session;
    el("s-ext").innerHTML = `${fmt(x.price)}<span class="${x.change_pct > 0 ? "bull" : x.change_pct < 0 ? "bear" : ""}">${change}</span> <small class="muted">at ${at}</small>`;
    extLine = candles.createPriceLine({
      price: x.price, color: C.extLine, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: x.session,
    });
  }

  // ---- watchlist ----

  function renderWatchlist(list) {
    const groups = { stock: "Stocks", etf: "Indexes", crypto: "Crypto" };
    el("watchlist").innerHTML = Object.entries(groups).map(([kind, title]) =>
      `<span class="wl-group" title="${title}">${list.filter((a) => a.kind === kind).map((a) =>
        `<button type="button" class="chip" data-ticker="${a.ticker}" title="${a.name} · chart: ${a.coin}">${a.ticker}</button>`).join("")}</span>`).join("");
    el("watchlist").addEventListener("click", (e) => {
      const b = e.target.closest("[data-ticker]");
      if (!b) return;
      el("coin").value = b.dataset.ticker;
      load();
    });
  }

  function markWatchlist() {
    const t = state.report.asset.ticker;
    document.querySelectorAll("#watchlist .chip").forEach((b) => b.classList.toggle("on", b.dataset.ticker === t));
    el("news-ticker").textContent = t;
  }

  // ---- news and macro context, and the confidence score ----

  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const link = (s) => s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : esc(s.title);
  const ago = (ms) => {
    if (!ms) return "";
    const h = (Date.now() - ms) / 3_600_000;
    return h < 1 ? `${Math.max(1, Math.round(h * 60))}m ago` : h < 48 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`;
  };

  async function loadContext() {
    const seq = loadSeq;
    const ticker = state.report.asset.ticker;
    if (!state.context || state.context.asset.ticker !== ticker) {
      el("confidence").innerHTML = '<p class="muted">Reading the news, yields and Fed calendar…</p>';
      el("context-body").innerHTML = "";
    }
    try {
      const res = await fetch(`/api/context?coin=${encodeURIComponent(state.coin)}&interval=${state.interval}`);
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const ctx = await res.json();
      if (seq !== loadSeq || ctx.asset.ticker !== state.report.asset.ticker) return; // the user moved on
      state.context = ctx;
      renderConfidence(ctx);
      renderContext(ctx);
    } catch (err) {
      if (seq !== loadSeq) return;
      el("confidence").innerHTML = `<p class="error">Could not load the news and macro context: ${esc(err.message)}</p>`;
    }
  }

  function renderConfidence(ctx) {
    const head = `<p class="ctx-bias">Context for ${esc(ctx.asset.ticker)}: <b class="${ctx.bias > 0.1 ? "bull" : ctx.bias < -0.1 ? "bear" : ""}">${ctx.bias_label}</b></p>`;
    el("confidence").innerHTML = head + ctx.confidence.map((c) => {
      const reasons = c.reasons.slice(0, 5).map((r) =>
        `<li class="r-${r.effect}"><span>${{ supports: "▲", against: "▼", risk: "!" }[r.effect]}</span>${esc(r.label)}${r.points != null ? ` <small>${r.points}</small>` : ""}</li>`).join("");
      return `<div class="conf">
        <div class="conf-head"><span class="${c.direction === "long" ? "bull" : "bear"}">${c.direction === "long" ? "Long" : "Short"}</span>
          <span class="conf-num grade-${c.grade}">${c.confidence}<small>/100 ${c.grade}</small></span></div>
        <div class="conf-bar" title="chart ${c.chart_points} + context ${c.context_points} − event risk ${c.event_penalty}">
          <i class="b-chart" style="width:${c.chart_points}%"></i><i class="b-ctx" style="width:${Math.max(0, c.context_points - c.event_penalty)}%"></i><i class="b-risk" style="width:${Math.min(c.event_penalty, c.context_points)}%"></i></div>
        <p class="conf-split">Chart ${Math.round(c.chart_points)}/60 · Context ${Math.round(c.context_points)}/40${c.event_penalty ? ` · Event risk −${Math.round(c.event_penalty)}` : ""}${c.status === "none" ? " · capped at 40 without a setup" : ""}</p>
        <p class="conf-verdict">${esc(c.verdict)}</p>
        <ul class="reasons">${reasons}</ul></div>`;
    }).join("") + `<p class="muted small">Details and sources are on the <button type="button" class="link-btn" data-goto="news">News tab</button>.</p>`;
  }

  function renderContext(ctx) {
    const signal = { bullish: "Bullish", bearish: "Bearish", neutral: "Neutral", risk: "Event risk" };
    let html = "";
    {
      // the asset's own news first and full width, then everything else
      const order = (f) => f.key === "news" ? 0 : f.key === "macro_news" ? 2 : 1;
      const factors = ctx.factors.filter((f) => f.group !== "Deep research").sort((a, b) => order(a) - order(b));
      html += `<div class="factors">` + factors.map((f) => {
        if (f.key === "news") {
          // one box per story: the headline as its title, the publisher's summary inside
          const stories = f.sources.map((s) => {
            const t = s.tone > 0 ? "bullish" : s.tone < 0 ? "bearish" : "neutral";
            return `<article class="story"><header><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a><span class="sig sig-${t}">${signal[t]}</span></header>
              <p>${s.summary ? esc(s.summary) : '<span class="muted">No summary in the feed. Open the story to read it.</span>'}</p>
              <footer>${esc(s.source)}${s.published ? ` · ${ago(s.published)}` : ""}</footer></article>`;
          }).join("");
          return `<article class="factor wide"><small class="group">${esc(f.group)}</small><header><b>${esc(f.label)}</b><span class="sig sig-${f.signal}">${signal[f.signal]}</span></header><p>${esc(f.detail)} Tone is read from each headline's wording.</p><div class="stories">${stories || '<p class="muted">No stories naming it in the last 2 days.</p>'}</div></article>`;
        }
        const isNews = f.group === "Macro and politics";
        const sources = f.sources.length ? (isNews
          ? `<ul class="headlines">${f.sources.map((s) => `<li><span class="tone ${s.tone > 0 ? "bull" : s.tone < 0 ? "bear" : ""}">${s.tone > 0 ? "▲" : s.tone < 0 ? "▼" : "•"}</span>${link(s)} <small>${esc(s.source)} ${ago(s.published)}</small></li>`).join("")}</ul>`
          : `<p class="src">Source: ${f.sources.map(link).join(" · ")}</p>`) : "";
        return `<article class="factor${f.key === "news" ? " wide" : ""}"><small class="group">${esc(f.group)}</small><header><b>${esc(f.label)}</b><span class="sig sig-${f.signal}">${signal[f.signal]}</span></header><p>${esc(f.detail)}</p>${sources}</article>`;
      }).join("") + "</div>";
    }
    html += renderResearch(ctx);
    if (ctx.missing.length) html += `<p class="muted small">Not reachable just now, left out of the score: ${ctx.missing.map(esc).join("; ")}.</p>`;
    html += `<p class="muted small">${ctx.demo ? "Demo mode: these numbers are made up so you can see the layout." : `Fetched ${ago(ctx.fetched)}; refreshed every 10 minutes.`} Headline tone is read from keywords, so open the stories before relying on them.</p>`;
    el("context-body").innerHTML = html;
    const btn = el("research-btn");
    if (btn) btn.addEventListener("click", runResearch);
  }

  function renderResearch(ctx) {
    const b = ctx.research;
    let html = '<h3>Deep research</h3>';
    if (!b) {
      if (!ctx.research_available) {
        return html + '<p class="muted">Claude can search the web and read the stories for you, then write a cited bull and bear case. Add <code>ANTHROPIC_API_KEY=...</code> to the <code>.env</code> file next to run.py and restart to turn it on. Each run uses API credit, roughly $0.25 to $1.50.</p>';
      }
      const running = state.research || ctx.research_running;
      return html + `<p class="muted">Claude searches the web (earnings, yields, the Fed, politics, company news), reads the sources and writes a cited brief. Takes 1 to 3 minutes and uses API credit.</p>
        <button type="button" id="research-btn" ${running ? "disabled" : ""}>${running ? "Researching…" : `Deep research ${esc(ctx.asset.ticker)}`}</button>`;
    }
    const list = (xs) => (xs || []).map((x) => `<li>${esc(x)}</li>`).join("");
    const catalysts = (b.catalysts || []).map((c) => `<li><b>${esc(c.date)}</b> ${esc(c.event)}<small>${esc(c.why_it_matters)}</small></li>`).join("");
    const sources = (b.sources || []).slice(0, 12).map((s) => `<li>${link(s)}${s.cited ? "" : ' <small>(searched)</small>'}</li>`).join("");
    return html + `<div class="brief">
      <p><span class="sig sig-${b.bias === "bullish" ? "bullish" : b.bias === "bearish" ? "bearish" : "neutral"}">${esc(b.bias)} ${esc(b.strength)}/100</span> ${esc(b.summary)}</p>
      <div class="cases"><div><h4 class="bull">Bull case</h4><ul>${list(b.bull_case)}</ul></div><div><h4 class="bear">Bear case</h4><ul>${list(b.bear_case)}</ul></div></div>
      ${b.rates_and_fed ? `<p><b>Rates and Fed.</b> ${esc(b.rates_and_fed)}</p>` : ""}
      ${b.politics ? `<p><b>Politics.</b> ${esc(b.politics)}</p>` : ""}
      ${b.next_earnings ? `<p><b>Next earnings.</b> ${esc(b.next_earnings)}</p>` : ""}
      ${catalysts ? `<h4>Coming up</h4><ul class="catalysts">${catalysts}</ul>` : ""}
      <h4>Sources</h4><ol class="sources">${sources}</ol>
      <p class="muted small">${esc(b.searches)} web searches by ${esc(b.model)}, ${ago(b.created)}. Counts toward the score for an hour.
        <button type="button" id="research-btn" class="link-btn">Run again</button></p></div>`;
  }

  async function runResearch() {
    state.research = true;
    renderContext(state.context);
    try {
      const res = await fetch(`/api/research?coin=${encodeURIComponent(state.coin)}`, { method: "POST" });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    } catch (err) {
      setStatus(`Deep research failed: ${err.message}`, true);
    }
    state.research = false;
    loadContext();
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
      ...r.order_blocks.map((b) => ({ t: b.event_time, dir: b.direction, text: `New ${b.direction} order block ${fmt(b.bottom)} to ${fmt(b.top)}` })),
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

  // highest high (or lowest low) of the candles from the broken swing to a few candles after the break
  function extremeBetween(t0, t1, high) {
    const ks = state.report.candles.filter((k) => !k.ext);
    const step = ks.length > 1 ? ks[1].t - ks[0].t : 0;
    let best = null;
    for (const k of ks) {
      if (k.t < t0 || k.t > t1 + 3 * step) continue;
      const v = high ? k.h : k.l;
      if (best == null || (high ? v > best : v < best)) best = v;
    }
    return best;
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
    const since = r.candles[Math.max(0, r.candles.length - RECENT)].t;

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
      // Each break gets a small outlined label clear of the candles: above the highs for a bullish
      // break, below the lows for a bearish one, tied to the middle of its level by a thin leader line.
      const boxes = [];
      const events = r.structure.filter((e) => e.time >= since).slice(-STRUCTURE_LABELS);
      for (const e of events.reverse()) {
        const bull = e.direction === "bullish";
        const color = bull ? C.bull : C.bear;
        hline(e.swing_time, e.time, e.level, color, e.type === "CHoCH" ? [5, 3] : [], 1.5);
        const x0 = x(e.swing_time), x1 = x(e.time), yy = y(e.level);
        if (x1 == null || yy == null) continue;
        const ax = x0 == null ? x1 : (Math.max(x0, 0) + x1) / 2;
        const ext = extremeBetween(e.swing_time, e.time, bull);
        const text = `${bull ? "▲" : "▼"} ${e.type}`;
        ctx.font = "600 10px system-ui, sans-serif";
        const w = ctx.measureText(text).width + 10, h = 15;
        // sweep arrows sit on the same side (above bars for bearish sweeps, below for bullish), so clear them too
        const step = r.candles[1].t - r.candles[0].t;
        const perCandle = {};
        if (layerOn("sweeps")) for (const sw of r.sweeps) {
          if ((sw.direction === "bullish") !== bull && sw.time >= e.swing_time && sw.time <= e.time + 3 * step) perCandle[sw.time] = (perCandle[sw.time] ?? 0) + 1;
        }
        const arrows = Math.max(0, ...Object.values(perCandle));
        let py = (ext == null ? yy : y(ext)) + (bull ? -1 : 1) * (22 + arrows * 12);
        let left = ax - w / 2;
        // step further out until the label is clear of the labels already drawn
        for (let i = 0; i < 4 && boxes.some((b) => left < b.x + b.w + 4 && b.x < left + w + 4 && Math.abs(b.y - py) < h + 2); i++) py += bull ? -(h + 3) : h + 3;
        boxes.push({ x: left, y: py, w });
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.7;
        ctx.setLineDash([2, 2]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(ax, py + (bull ? h / 2 : -h / 2));
        ctx.lineTo(ax, yy);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
        ctx.fillStyle = C.labelBg;
        ctx.beginPath();
        ctx.roundRect(left, py - h / 2, w, h, 3);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = color;
        ctx.textBaseline = "middle";
        ctx.fillText(text, left + 5, py + 0.5);
        ctx.textBaseline = "alphabetic";
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
    clearInterval(pollTimer);
    if (state.report.source === "yahoo") { pollTimer = setInterval(refresh, 60_000); return; }
    if (state.report.source !== "hyperliquid") return;
    const coin = state.report.asset.coin;
    const sub = { type: "candle", coin, interval: state.interval };
    ws = new WebSocket(HL_WS);
    ws.onopen = () => ws.send(JSON.stringify({ method: "subscribe", subscription: sub }));
    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.channel !== "candle") return;
      const k = data.data;
      if (k.s !== coin || k.i !== state.interval) return;
      const t = Number(k.t);
      const off = state.report.asset.kind !== "crypto" && isExtended(t);
      if (off && !state.report.ext) return; // regular hours only: leave the perp's off-hours trading out
      const color = off ? (+k.c >= +k.o ? C.extBull : C.extBear) : undefined;
      candles.update({ time: sec(t), open: +k.o, high: +k.h, low: +k.l, close: +k.c, ...(color && { color, wickColor: color }) });
      volume.update({ time: sec(t), value: +k.v, color: +k.c >= +k.o ? `rgba(8,153,129,${off ? 0.12 : 0.3})` : `rgba(242,54,69,${off ? 0.12 : 0.3})` });
      el("s-price").textContent = fmt(+k.c);
      if (lastBarTime != null && t > lastBarTime) {
        // the previous candle just closed: re-run the detectors on closed data
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(refresh, 1500);
      }
      lastBarTime = Math.max(lastBarTime ?? 0, t);
    };
    const me = ws;
    ws.onclose = () => { setTimeout(() => { if (ws === me) connectLive(); }, 3000); }; // reconnect only if still current
  }

  async function refresh() {
    const seq = loadSeq;
    try {
      const res = await fetch(analysisUrl());
      if (!res.ok || seq !== loadSeq) return;
      const report = await res.json();
      if (seq !== loadSeq) return;
      state.report = report;
      render(false);
      await window.Strategy?.market(state.report.asset, false);
      if (seq !== loadSeq) return;
      loadContext();
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
  extBox.addEventListener("change", () => {
    try { localStorage.setItem("ma-ext", extBox.checked ? "1" : "0"); } catch { /* not remembered, still applies */ }
    load();
  });
  document.querySelectorAll("[data-layer]").forEach((box) => box.addEventListener("change", () => state.report && render(false)));
  new ResizeObserver(resizeOverlay).observe(chartEl);
  resizeOverlay();
  requestAnimationFrame(loop);

  window.Strategy?.init({ open: (ticker) => { el("coin").value = ticker; window.Tabs?.show("chart"); load(); } });
  fetch("/api/config").then((r) => r.json()).then((cfg) => { state.demo = cfg.demo; el("version").textContent = `v${cfg.version}`; renderWatchlist(cfg.watchlist); load(); });
})();
