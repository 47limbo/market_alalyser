// The strategy panels: today's drivers, the sector board, the shortlist and Timeframe Alignment.
// app.js calls Strategy.init() once and Strategy.market() for every market it loads. Read-only, like the rest.
window.Strategy = (() => {
  const el = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const num = (x, d = 2) => x == null ? "–" : Number(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  const signed = (x, d = 1) => x == null ? "–" : `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}`;
  const tone = (x, cut = 15) => x > cut ? "bull" : x < -cut ? "bear" : "";
  const time = (ms) => new Date(ms).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });
  const BOARD_MS = 120_000;

  let open = () => {};
  let board = null;
  let asset = null;
  let picked = null; // the board row opened to show its reasons
  let showAll = false;
  const EDGE = 6; // rows shown from each end of the board until "show all"
  const SHORT = { theme: "Theme", liquidity: "Liquid", room: "Room", conflict: "Own news", laggard: "Laggard", rs: "RS" };
  let direction = "auto";
  let wanted = null; // {ticker, dir} chosen on the shortlist before the chart switches
  let timer = null;

  const settings = (() => {
    try { return { amount: 1000, risk: 5, ...JSON.parse(localStorage.getItem("ma-risk") || "{}") }; } catch { return { amount: 1000, risk: 5 }; }
  })();
  const save = () => { try { localStorage.setItem("ma-risk", JSON.stringify(settings)); } catch { /* private window */ } };

  async function get(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    return res.json();
  }

  // ---- Stages 1 to 3 ----

  async function loadBoard() {
    clearTimeout(timer);
    timer = setTimeout(loadBoard, BOARD_MS);
    if (!board) el("board").innerHTML = '<p class="muted">Reading yields, oil, the dollar, the calendar and about 170 stocks and ETFs…</p>';
    try {
      board = await get("/api/board");
    } catch (err) {
      el("board").innerHTML = `<p class="error">Could not build the sector board: ${esc(err.message)}</p>`;
      return;
    }
    renderDrivers();
    renderBoard();
    loadShortlist();
  }

  // one titled section of the Market today page
  const block = (title, sub, body, extra = "") =>
    `<section class="block ${extra}"><header class="block-head"><h3>${title}</h3>${sub ? `<p>${sub}</p>` : ""}</header><div class="block-body">${body}</div></section>`;
  const day = (ms) => new Date(ms).toLocaleString(undefined, { weekday: "short" });
  const clock = (ms) => new Date(ms).toLocaleString(undefined, { hour: "2-digit", minute: "2-digit" });
  // "cooler than expected (-1.0 typical misses)." -> "Cooler than expected"
  const outcome = (note) => { const t = String(note || "").replace(/\s*\(.*$/, "").replace(/\.$/, ""); return t.charAt(0).toUpperCase() + t.slice(1); };

  function renderDrivers() {
    const b = board;
    const chips = b.drivers.map((d) => {
      const t = d.z > 0.5 ? "up" : d.z < -0.5 ? "down" : "";
      return `<a class="drv ${t}" href="${esc(d.url)}" target="_blank" rel="noopener" title="${esc(d.change)} (${signed(d.z)} typical days)">
        <small>${esc(d.label)}</small><b>${esc(d.value)}</b><span>${t === "up" ? "▲ " : t === "down" ? "▼ " : ""}${esc(d.change)}</span></a>`;
    }).join("");
    const now = Date.now();
    const releases = b.releases.filter((r) => r.impact === "High" || r.surprise != null).slice(-10).map((r) => {
      const t = r.surprise == null ? (r.actual ? "flat" : "later") : r.surprise > 0.5 ? "hot" : r.surprise < -0.5 ? "cool" : "flat";
      return `<tr class="${r.time > now ? "later" : ""}">
        <td class="when"><b>${esc(day(r.time))}</b><small>${esc(clock(r.time))}</small></td>
        <td class="what">${esc(r.title)}</td>
        <td class="n">${r.actual ? `<b>${esc(r.actual)}</b>` : '<span class="muted">–</span>'}</td>
        <td class="n muted">${esc(r.consensus || "–")}</td>
        <td><span class="res res-${t}" title="${esc(r.note)}">${esc(outcome(r.note))}</span></td></tr>`;
    }).join("");
    const leaders = b.leaders.map((l) => `<li>
        <div class="ld-top"><b class="ld-tk">${esc(l.ticker)}</b><span class="${tone(l.excess, 0)}">${signed(l.excess)}% vs SPY</span><small class="muted">${signed(l.z)}σ move</small></div>
        ${l.why ? `<p class="muted small">${esc(l.why)}</p>` : ""}
        <p class="ld-fx"><span class="muted">Moves</span> ${l.niches.map((n) => `<button type="button" class="tk" data-open="${esc(n)}">${esc(n)}</button>`).join("")}
          ${l.capex ? `<span class="muted">Spending news lifts</span> ${l.capex_niches.map((n) => `<button type="button" class="tk" data-open="${esc(n)}">${esc(n)}</button>`).join("")}` : ""}</p></li>`).join("");
    const mood = `<div class="mood"><span class="pill">${esc(b.regime_label)}</span><span>${esc(b.regime_note)}</span></div>
      ${b.rotation ? `<div class="rotation" role="status"><b>Rotation alert</b><span>${esc(b.rotation)}</span></div>` : ""}`;
    el("drivers").innerHTML =
      block("Market mood and drivers", "How yields, oil, the dollar, VIX and copper moved today. An orange edge means an unusually large rise, blue an unusually large fall.",
        `${mood}<div class="drvs">${chips || '<p class="muted">No market prices reachable.</p>'}</div>`) +
      `<div class="cols">` +
      block("Economic calendar", "This week's high-impact US releases: what came out against what was expected.",
        releases ? `<div class="table-wrap"><table class="cal"><thead><tr><th>When</th><th>Release</th><th class="n">Actual</th><th class="n">Expected</th><th>Result</th></tr></thead><tbody>${releases}</tbody></table></div>`
          : '<p class="muted">Calendar not reachable.</p>') +
      block("Leaders moving their group", "Big names that made an unusual move today, and the niches they drag with them.",
        `<ul class="leaders">${leaders || '<li class="muted">No leader has made an unusual move today.</li>'}</ul>
        ${b.tomorrow.length ? `<div class="next-risk"><b>Next session event risk</b><span>${b.tomorrow.map((r) => esc(r.title)).join(", ")}</span></div>` : ""}`) +
      `</div>`;
  }

  function bar(score) {
    const w = Math.min(50, Math.abs(score) / 2);
    return `<span class="sbar"><i class="${score >= 0 ? "pos" : "neg"}" style="${score >= 0 ? "left:50%" : `left:${50 - w}%`};width:${w}%"></i></span>`;
  }

  function renderBoard() {
    const b = board;
    const keep = (r, i) => showAll || i < EDGE || i >= b.rows.length - EDGE || r.etf === picked;
    const hiddenCount = b.rows.filter((r, i) => !keep(r, i)).length;
    const rows = b.rows.filter(keep).map((r, i, shown) => `
      ${i > 0 && shown[i - 1].rank + 1 !== r.rank ? `<tr class="gap"><td></td><td colspan="9"><button type="button" class="link-btn" data-all="1">Show ${hiddenCount} more niches</button></td></tr>` : ""}
      <tr data-etf="${r.etf}" class="${r.etf === picked ? "on" : ""} ${b.bull.includes(r.etf) || b.bear.includes(r.etf) ? "pick" : ""}">
        <td class="rk">${r.rank}</td>
        <td><button type="button" class="link-btn" data-open="${r.etf}" title="Chart ${r.etf}">${esc(r.etf)}</button> ${esc(r.name)}</td>
        <td class="sc"><b class="${tone(r.score, 19)}">${signed(r.score, 0)}</b>${bar(r.score)}</td>
        <td><span class="lbl ${tone(r.score, 19)}">${esc(r.label)}</span></td>
        <td class="n ${tone(r.news)}">${signed(r.news, 0)}</td><td class="n ${tone(r.rs)}">${signed(r.rs, 0)}</td><td class="n ${tone(r.flow)}">${signed(r.flow, 0)}</td><td class="n ${tone(r.breadth)}">${signed(r.breadth, 0)}</td>
        <td class="n ${tone(r.excess, 0.25)}">${signed(r.excess)}%</td>
        <td class="read" title="${esc(r.action)}">${esc(r.read)}</td>
      </tr>
      <tr class="why ${r.etf === picked ? "" : "hidden"}" data-why="${r.etf}"><td></td><td colspan="9">
        <ul>${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <p class="small"><b>${esc(r.action)}.</b>${r.next_session ? ` Next session: ${esc(r.next_session)}.` : ""}</p></td></tr>`).join("");
    const hit = b.hit_rate ? `<span class="stat"><small>Yesterday's calls</small><b>${b.hit_rate.last ? `${b.hit_rate.last.right} of ${b.hit_rate.last.total} right` : "Not scored yet"}</b></span>
      <span class="stat"><small>Last ${b.hit_rate.total} calls</small><b>${Math.round(b.hit_rate.rate * 100)}% right</b></span>` : "";
    el("board").innerHTML = `
      <div class="board-meta">${hit}<span class="legend"><i class="pick-mark"></i> Goes to the shortlist</span></div>
      <div class="table-wrap"><table class="board-table">
        <thead><tr><th>#</th><th>Niche</th><th>Score</th><th>Call</th><th class="n" title="News impulse: drivers and leader moves through the sensitivity matrix">News</th><th class="n" title="Relative strength vs SPY: today, yesterday, 5 days">RS</th><th class="n" title="Volume vs normal, signed by direction">Flow</th><th class="n" title="Holdings up today and above their 20-day average">Breadth</th><th class="n">vs SPY</th><th>Read</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <p class="note">Score = 40% news impulse + 30% relative strength + 15% flow + 15% breadth.
        ${b.missing.length ? ` Not reachable: ${b.missing.map(esc).join("; ")}.` : ""}${b.demo ? " Demo data: made up so you can see the layout." : ""}</p>`;
  }

  // ---- Stage 4 ----

  async function loadShortlist() {
    if (!el("shortlist").innerHTML) el("shortlist").innerHTML = '<p class="muted">Checking the names in the top niches…</p>';
    try {
      renderShortlist(await get("/api/shortlist"));
    } catch (err) {
      el("shortlist").innerHTML = `<p class="error">Could not build the shortlist: ${esc(err.message)}</p>`;
    }
  }

  function renderShortlist(s) {
    el("shortlist").innerHTML = s.groups.length ? `<div class="sl-grid">${s.groups.map((g) => `
      <div class="sl-group"><div class="sl-head"><span class="dir dir-${g.direction}">${g.direction === "long" ? "Long" : "Short"}</span>
        <b>${esc(g.name)}</b><span class="muted">${esc(g.etf)} · score ${signed(g.score, 0)}</span></div>
        ${g.candidates.map((c) => `
          <button type="button" class="cand ${c.qualifies ? "ok" : ""} ${asset && asset.ticker === c.ticker ? "on" : ""}" data-open="${c.ticker}" data-dir="${g.direction}">
            <span class="cand-top"><b>${esc(c.ticker)}</b> <span class="muted">${esc(c.name)}</span><span class="${tone(c.today, 0)}">${signed(c.today)}%</span></span>
            <span class="cand-checks">${c.checks.map((k) => `<i class="k-${k.status}" title="${esc(k.label)}: ${esc(k.detail)}">${k.status === "pass" ? "✓" : k.status === "fail" ? "✗" : "–"} ${SHORT[k.key] || esc(k.label)}</i>`).join("")}</span>
            <span class="cand-foot"><span class="${c.qualifies ? "q-yes" : "q-no"}">${c.qualifies ? "Qualifies" : "Fails a required check"}</span><span class="muted">fit ${Math.round(c.fit * 100)}%</span></span>
          </button>`).join("") || '<p class="muted small">No liquid names found.</p>'}
      </div>`).join("")}</div>` : '<p class="muted">No niche stands out today.</p>';
  }

  // ---- Stage 5 ----

  async function loadAlignment() {
    if (!asset) return;
    const box = el("alignment");
    if (asset.kind === "crypto") {
      box.innerHTML = '<p class="muted">The strategy covers US stocks and index ETFs. Pick one from the shortlist or the watchlist.</p>';
      return;
    }
    const ticker = asset.ticker;
    if (!box.dataset.ticker || box.dataset.ticker !== ticker) box.innerHTML = `<p class="muted">Checking ${esc(ticker)} on Daily, 4H, 1H, 15m and 5m…</p>`;
    box.dataset.ticker = ticker;
    try {
      const dir = direction === "auto" ? "" : `&direction=${direction}`;
      const a = await get(`/api/alignment?coin=${encodeURIComponent(ticker)}${dir}&amount=${settings.amount}&risk_pct=${settings.risk}`);
      if (!asset || asset.ticker !== ticker) return;
      renderAlignment(a);
    } catch (err) {
      box.innerHTML = `<p class="error">Could not check the timeframes: ${esc(err.message)}</p>`;
    }
  }

  function renderAlignment(a) {
    const mark = { pass: "✓", wait: "…", conflict: "✗" };
    const cards = a.cards.map((c) => `
      <div class="tf tf-${c.status}"><div class="tf-head"><b>${esc(c.name)}</b><small>${esc(c.role)}</small><span>${mark[c.status]}</span></div>
        <p>${esc(c.summary)}</p>
        <ul>${c.checks.map((k) => `<li class="k-${k.status}">${k.status === "pass" ? "✓" : k.status === "fail" ? "✗" : "–"} ${esc(k.label)}${k.detail ? ` <small>${esc(k.detail)}</small>` : ""}</li>`).join("")}</ul></div>`).join("");
    const p = a.plan;
    const plan = p ? `
      <dl class="plan-dl"><dt>Entry</dt><dd>${num(p.entry)}</dd><dt>Stop</dt><dd class="bear">${num(p.stop)}</dd>
        <dt>Target</dt><dd class="bull">${num(p.target)}${p.reward_risk != null ? ` (${p.reward_risk}R)` : ""}</dd>
        <dt>Size</dt><dd>${p.size.shares} shares, $${num(p.size.notional, 0)}</dd>
        <dt>Loss at stop</dt><dd class="bear">−$${num(p.size.loss_at_stop)}</dd>
        ${p.size.gain_at_target != null ? `<dt>Gain at target</dt><dd class="bull">+$${num(p.size.gain_at_target)}</dd>` : ""}</dl>
      ${p.size.reduced ? `<p class="small muted">Stop is ${p.size.stop_pct}% away, so the position is cut below $${num(p.size.amount, 0)} to keep the loss under $${num(p.size.max_loss, 0)}.</p>` : ""}`
      : '<p class="small muted">No entry, stop and target yet: they come from the 5m setup.</p>';
    const n = a.niche;
    el("alignment").innerHTML = `
      <div class="dir-pick" role="group" aria-label="Direction">${["auto", "long", "short"].map((d) => `<button type="button" data-dir="${d}" class="${direction === d ? "on" : ""}">${d === "auto" ? "Auto" : d === "long" ? "Long" : "Short"}</button>`).join("")}</div>
      <div class="verdict v-${a.verdict.toLowerCase()}"><b>${esc(a.verdict)}</b> <span>${a.direction === "long" ? "Long" : "Short"} ${esc(a.ticker)}</span><small>${esc(a.why)}</small></div>
      ${n ? `<p class="small">Niche: <b>${esc(n.name)}</b> ${esc(n.label)} (${signed(n.score, 0)}), ${esc(n.read.toLowerCase())}.</p>` : '<p class="small muted">Not in a board niche, so the direction comes from the daily trend.</p>'}
      ${a.warnings.map((w) => `<p class="warn">${esc(w)}</p>`).join("")}
      <div class="tfs">${cards}</div>
      ${plan}
      <p class="strat-conf">Strategy confidence <b>${a.confidence}</b><small>/100</small>
        <span class="muted small">niche ${Math.round(a.parts.niche * 100)}% × ticker ${Math.round(a.parts.ticker * 100)}% × timeframes ${Math.round(a.parts.alignment * 100)}%</span></p>
      <div class="risk-set"><label>Entry $ <input type="number" id="r-amount" min="1" step="50" value="${settings.amount}"></label>
        <label>Risk % <input type="number" id="r-risk" min="0.1" max="100" step="0.5" value="${settings.risk}"></label>
        <span class="small muted">max loss $${num(settings.amount * settings.risk / 100, 0)}</span></div>`;
  }

  // ---- wiring ----

  function init(opts) {
    open = opts.open;
    document.addEventListener("click", (e) => {
      const t = e.target.closest("[data-open]");
      if (t && (t.closest("#strategy") || t.closest("#alignment-card"))) {
        wanted = { ticker: t.dataset.open, dir: t.dataset.dir || "auto" };
        open(t.dataset.open);
        return;
      }
      if (e.target.closest("[data-all]")) { showAll = true; renderBoard(); return; }
      const row = e.target.closest("tr[data-etf]");
      if (row) {
        picked = picked === row.dataset.etf ? null : row.dataset.etf;
        renderBoard();
        return;
      }
      const d = e.target.closest(".dir-pick [data-dir]");
      if (d) { direction = d.dataset.dir; loadAlignment(); }
    });
    document.addEventListener("change", (e) => {
      if (e.target.id === "r-amount" || e.target.id === "r-risk") {
        const v = Number(e.target.value);
        if (!(v > 0)) return;
        settings[e.target.id === "r-amount" ? "amount" : "risk"] = v;
        save();
        loadAlignment();
      }
    });
    loadBoard();
  }

  // called for every market the chart loads; resolves once the alignment (which feeds the confidence) is in
  async function market(a, fresh) {
    if (fresh && (!asset || asset.ticker !== a.ticker)) direction = wanted && wanted.ticker === a.ticker ? wanted.dir : "auto";
    wanted = null;
    asset = a;
    document.querySelectorAll("#shortlist .cand").forEach((b) => b.classList.toggle("on", b.dataset.open === a.ticker));
    await loadAlignment();
  }

  return { init, market };
})();
