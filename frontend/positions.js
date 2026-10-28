// The Positions tab: the user's holdings valued at live prices, with add, edit and remove.
// The list is saved by the server in data/positions.json; prices refresh every 30 seconds. Read-only like the rest:
// nothing here places or changes an order at a broker.
window.Positions = (() => {
  const el = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const REFRESH_MS = 30_000;
  const NEAR_STOP = 2; // % from the stop that counts as close

  let held = [];
  let quotes = {};
  let editing = null; // index being edited, or null when adding
  let timer = null;
  let open = () => {};

  const money = (x, d = 2) => x == null || !isFinite(x) ? "–"
    : `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}`;
  const signedMoney = (x) => x == null ? "–" : `${x > 0 ? "+" : ""}${money(x)}`;
  const pct = (x, d = 2) => x == null || !isFinite(x) ? "–" : `${x > 0 ? "+" : ""}${x.toFixed(d)}%`;
  const tone = (x) => x > 0 ? "bull" : x < 0 ? "bear" : "";
  // crypto can trade at fractions of a cent, so show more decimals on small prices
  const price = (x) => x == null ? "–" : money(x, x < 1 ? 4 : 2);
  const signedPrice = (x) => `${x > 0 ? "+" : ""}${x < 0 ? "−" : ""}${price(Math.abs(x))}`;
  const qtyText = (q) => Math.abs(q).toLocaleString(undefined, { maximumFractionDigits: 6 });

  async function call(method = "GET", body) {
    const res = await fetch("/api/positions", body ? { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { method });
    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))).detail;
      throw new Error(Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail || res.statusText);
    }
    const data = await res.json();
    held = data.positions;
    quotes = data.quotes;
    el("pos-updated").textContent = `${data.demo ? "Demo prices" : "Prices"} as of ${new Date().toLocaleTimeString()}`;
  }

  async function refresh() {
    clearTimeout(timer);
    timer = setTimeout(refresh, REFRESH_MS);
    try {
      await call();
      el("pos-error").hidden = true;
    } catch (err) {
      showError(`Could not load prices: ${err.message}`);
    }
    render();
  }

  function showError(text) {
    el("pos-error").textContent = text;
    el("pos-error").hidden = false;
  }

  // one row's numbers; a short (negative quantity) gains when the price falls
  function value(p) {
    const q = quotes[p.symbol] || {};
    const last = q.price;
    const has = last != null;
    const basis = Math.abs(p.qty) * p.cost;
    const pl = has ? (last - p.cost) * p.qty : null;
    const day = has && q.prev_close ? (last - q.prev_close) * p.qty : null;
    let stopGap = null;
    if (p.stop && has) stopGap = p.qty > 0 ? (last - p.stop) / last * 100 : (p.stop - last) / last * 100;
    return { q, last, mv: has ? Math.abs(p.qty) * last : null, basis, pl, ret: pl == null ? null : pl / basis * 100, day,
      dayPct: has && q.prev_close ? (last / q.prev_close - 1) * 100 : null, stopGap };
  }

  function render() {
    const rows = held.map((p, i) => ({ p, i, v: value(p) }));
    const sum = (f) => rows.reduce((a, r) => a + (f(r) ?? 0), 0);
    const long = sum((r) => r.p.qty > 0 ? r.v.mv : 0);
    const short = sum((r) => r.p.qty < 0 ? r.v.mv : 0);
    const pl = sum((r) => r.v.pl);
    const basis = sum((r) => r.v.basis);
    const day = sum((r) => r.v.day);
    const gross = long + short;

    el("pos-summary").innerHTML = [
      tile("Long value", money(long), `${rows.filter((r) => r.p.qty > 0).length} positions`),
      tile("Short value", money(short), `${rows.filter((r) => r.p.qty < 0).length} positions`),
      tile("Total P/L", signedMoney(pl), pct(basis ? pl / basis * 100 : null), tone(pl)),
      tile("Today", signedMoney(day), "since the previous close", tone(day)),
    ].join("");

    const groups = [["stock", "Stocks and ETFs"], ["crypto", "Crypto"]];
    el("pos-tables").innerHTML = rows.length ? groups.map(([kind, title]) => {
      const g = rows.filter((r) => r.p.kind === kind);
      if (!g.length) return "";
      const gpl = g.reduce((a, r) => a + (r.v.pl ?? 0), 0);
      const gmv = g.reduce((a, r) => a + (r.v.mv ?? 0), 0);
      return `<section class="card pos-group">
        <div class="pos-group-head"><h2>${title}</h2>
          <span class="muted small">${g.length} held · ${money(gmv)} · <b class="${tone(gpl)}">${signedMoney(gpl)}</b></span></div>
        <div class="pos-scroll"><table class="pos-table">
          <thead><tr><th>Symbol</th><th class="num">Quantity</th><th class="num">Price paid</th><th class="num">Last price</th>
            <th class="num">Day's change</th><th class="num">Market value</th><th class="num">Profit / loss</th>
            <th class="num">% return</th><th class="num">Weight</th><th>Stop</th><th></th></tr></thead>
          <tbody>${g.map((r) => row(r, gross)).join("")}</tbody>
        </table></div>
      </section>`;
    }).join("") : '<section class="card"><p class="muted">No positions yet. Add one below.</p></section>';
  }

  const tile = (label, big, small, cls = "") =>
    `<div class="pos-tile"><small>${label}</small><b class="${cls}">${big}</b><span class="${cls}">${small}</span></div>`;

  function row({ p, i, v }, gross) {
    const side = p.qty < 0 ? '<span class="pos-side short">Short</span>' : '<span class="pos-side long">Long</span>';
    const ext = v.q.ext_price != null && v.q.ext_price !== v.last
      ? `<small class="muted" title="Latest pre-market or after-hours trade">ext ${price(v.q.ext_price)}</small>` : "";
    const stale = v.q.error ? `<small class="bear" title="${esc(v.q.error)}">no price</small>`
      : v.q.stale ? '<small class="muted" title="The source did not answer; showing the last price it gave">stale</small>' : "";
    let stop = '<span class="muted">–</span>';
    if (p.stop) {
      const near = v.stopGap != null && v.stopGap < NEAR_STOP;
      stop = `<span class="${near ? "pos-near" : ""}" title="${p.qty > 0 ? "Stop order to sell" : "Stop order to buy back"} at ${price(p.stop)}">
        ${price(p.stop)} <small>${v.stopGap == null ? "" : v.stopGap <= 0 ? "hit" : `${v.stopGap.toFixed(1)}% away`}</small></span>`;
    }
    return `<tr class="${editing === i ? "editing" : ""}">
      <td><button type="button" class="pos-sym" data-open="${esc(p.symbol)}" title="Open the ${esc(p.symbol)} chart">${esc(p.symbol)}</button> ${side}
        ${p.note ? `<div class="muted small">${esc(p.note)}</div>` : ""}</td>
      <td class="num">${qtyText(p.qty)}</td>
      <td class="num">${price(p.cost)}</td>
      <td class="num"><b>${price(v.last)}</b> ${ext}${stale}</td>
      <td class="num ${tone(v.dayPct)}">${pct(v.dayPct)}<div class="small">${v.last != null && v.q.prev_close ? signedPrice(v.last - v.q.prev_close) : ""}</div></td>
      <td class="num">${money(v.mv)}</td>
      <td class="num ${tone(v.pl)}"><b>${signedMoney(v.pl)}</b></td>
      <td class="num ${tone(v.ret)}">${pct(v.ret)}</td>
      <td class="num muted">${v.mv != null && gross ? (v.mv / gross * 100 < 0.1 ? "<0.1%" : `${(v.mv / gross * 100).toFixed(1)}%`) : "–"}</td>
      <td>${stop}</td>
      <td class="pos-actions"><button type="button" class="ghost" data-edit="${i}">Edit</button>
        <button type="button" class="ghost danger" data-remove="${i}">Remove</button></td>
    </tr>`;
  }

  // ---- the add / edit form ----

  function fill(p) {
    const f = el("pos-form");
    f.symbol.value = p?.symbol ?? "";
    f.kind.value = p?.kind ?? "stock";
    f.side.value = p && p.qty < 0 ? "short" : "long";
    f.qty.value = p ? Math.abs(p.qty) : "";
    f.cost.value = p?.cost ?? "";
    f.stop.value = p?.stop ?? "";
    f.note.value = p?.note ?? "";
    el("pos-form-title").textContent = p ? `Edit ${p.symbol}` : "Add a position";
    el("pos-submit").textContent = p ? "Save changes" : "Add position";
    el("pos-cancel").hidden = !p;
  }

  function startEdit(i) {
    editing = i;
    fill(held[i]);
    render();
    el("pos-form").scrollIntoView({ behavior: "smooth", block: "center" });
    el("pos-form").qty.focus();
  }

  function stopEdit() {
    editing = null;
    fill(null);
    render();
  }

  async function save(next) {
    try {
      await call("PUT", next);
      el("pos-error").hidden = true;
      return true;
    } catch (err) {
      showError(`Not saved: ${err.message}`);
      return false;
    } finally {
      render();
    }
  }

  async function submit(e) {
    e.preventDefault();
    const f = e.target;
    const qty = Number(f.qty.value);
    const p = {
      symbol: f.symbol.value.trim().toUpperCase(),
      kind: f.kind.value,
      qty: f.side.value === "short" ? -qty : qty,
      cost: Number(f.cost.value),
      stop: f.stop.value ? Number(f.stop.value) : null,
      note: f.note.value.trim(),
    };
    const next = [...held];
    if (editing == null) next.push(p); else next[editing] = p;
    if (await save(next)) stopEdit();
  }

  // Remove asks once more on the same button, so a stray click does not delete a row
  let armed = null;
  async function remove(btn, i) {
    if (armed !== btn) {
      armed = btn;
      btn.textContent = "Sure?";
      setTimeout(() => { if (armed === btn) { armed = null; btn.textContent = "Remove"; } }, 3000);
      return;
    }
    armed = null;
    if (editing === i) editing = null; else if (editing != null && editing > i) editing--;
    await save(held.filter((_, k) => k !== i));
  }

  function init(opts) {
    open = opts.open;
    el("pos-form").addEventListener("submit", submit);
    el("pos-cancel").addEventListener("click", stopEdit);
    el("pos-refresh").addEventListener("click", refresh);
    el("pos-tables").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.open) open(b.dataset.open);
      else if (b.dataset.edit) startEdit(Number(b.dataset.edit));
      else if (b.dataset.remove) remove(b, Number(b.dataset.remove));
    });
    fill(null);
    refresh();
  }

  return { init };
})();
