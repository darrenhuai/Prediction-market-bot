// Prediction Market Bot UI. Plain JavaScript, no build step.
const $ = (sel) => document.querySelector(sel);
const PAGE = 60;
let state = null;
let shown = PAGE;
let lastUpdated = null;

// ---------- formatting ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const cents = (c) => (c == null ? "–" : `${+c.toFixed(1)}¢`);
const signed = (c) => `${c >= 0 ? "+" : "−"}${Math.abs(c).toFixed(1)}¢`;
const pct = (p) => (p == null ? "–" : `${Math.round(p)}%`);
const money = (d) => `$${d.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: d < 100 ? 2 : 0 })}`;
const compact = (n) => (n ? Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n) : "0");
const tradable = (p) => p != null && p > 0 && p < 100;

function relTime(iso, future = false) {
  if (!iso) return "";
  const diff = (new Date(iso) - Date.now()) / 1000;
  const a = Math.abs(diff);
  const [n, unit] = a < 60 ? [0, "now"] : a < 3600 ? [Math.round(a / 60), "min"] : a < 86400 ? [Math.round(a / 3600), "hr"] : [Math.round(a / 86400), "day"];
  if (unit === "now") return "just now";
  const label = `${n} ${unit}${n > 1 && unit !== "min" ? "s" : ""}`;
  return future || diff > 0 ? `in ${label}` : `${label} ago`;
}

// ---------- expected value (mirrors src/scanner/signals.py) ----------
function fee(price) {
  const p = price / 100;
  return state.settings.fee_rate * p * (1 - p) * 100;
}
function evaluate(prob, m) {
  const side = (winProb, ask) => {
    if (!tradable(ask)) return null;
    const cost = ask + fee(ask);
    const ev = winProb * 100 - cost;
    const kelly = Math.max(0, (winProb - cost / 100) / (1 - cost / 100)) * 0.25;
    return { price: ask, cost, ev, kelly };
  };
  return { yes: side(prob, m.yes_ask), no: side(1 - prob, m.no_ask) };
}

// ---------- data ----------
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function load() {
  state = await api("/api/state");
  state.byTicker = Object.fromEntries(state.markets.map((m) => [m.ticker, m]));
  lastUpdated = state.updated_at;
  render();
}

async function poll() {
  try {
    const s = await api("/api/status");
    $("#refresh").disabled = s.refreshing;
    $("#refresh").textContent = s.refreshing ? "Refreshing…" : "Refresh";
    if (s.updated_at !== lastUpdated || (s.error || null) !== (state?.error || null)) await load();
    else renderStatus();
  } catch {
    $("#updated").textContent = "App is not running";
  }
}

// ---------- rendering ----------
function render() {
  renderStatus();
  renderOpps();
  renderCategories();
  renderMarkets();
  renderPicks();
  renderSettings();
}

function renderStatus() {
  $("#mode").hidden = state.mode !== "demo";
  $("#updated").textContent = state.updated_at ? `Updated ${relTime(state.updated_at)} · ${state.markets.length.toLocaleString()} markets` : state.error ? "No market data yet" : "Loading markets…";
  $("#balance").textContent = state.balance != null ? `Balance ${money(state.balance)}` : "";
  const err = $("#error");
  err.hidden = !state.error;
  const kept = state.markets.length ? " Showing the last data we had." : "";
  err.textContent = state.error ? `${state.error}.${kept} Check your internet connection, or try the app with made-up data: uv run app.py --demo` : "";
}

function empty(text) {
  return `<div class="empty">${text}</div>`;
}

function renderOpps() {
  const { picks, arbitrage, flow } = state.opportunities;
  $("#count-opps").textContent = picks.length + arbitrage.length + flow.length || "";

  $("#opps-picks").innerHTML = picks.length
    ? picks.map((o) => `
      <div class="card">
        <span class="tag good">Buy ${o.side}</span>
        <h3>${esc(o.title)}</h3>
        <p class="big good">${signed(o.ev_cents)} <small>per contract</small></p>
        <p>Buy ${o.side} at <b>${cents(o.price)}</b>. You say ${pct(o.your_chance)} chance of YES; the market says ${pct(o.market_chance)}.</p>
        ${o.suggested_stake ? `<p>Suggested stake: <b>${money(o.suggested_stake)}</b> (${o.contracts} contracts)</p>` : ""}
        <button class="btn secondary" data-open="${esc(o.ticker)}">Details</button>
      </div>`).join("")
    : empty(Object.keys(state.estimates).length
      ? "None of your picks has an edge at today's prices. The bot keeps checking."
      : "You haven't added any picks yet. Open the <b>Markets</b> tab, tap a market, and enter the chance you think it has.");

  $("#opps-arbitrage").innerHTML = arbitrage.length
    ? arbitrage.map((o) => `
      <div class="card">
        <span class="tag ${o.guaranteed ? "good" : "warn"}">${o.guaranteed ? "Locked in" : "Needs one outcome to win"}</span>
        <h3>${esc(o.title)}</h3>
        <p class="big good">${signed(o.profit_cents)} <small>per bundle</small></p>
        <p>Buy <b>${o.side}</b> on all ${o.legs.length} outcomes for ${cents(o.cost_cents)} (fees included). Pays at least ${cents(o.payout_cents)}.</p>
        <ul class="legs">${o.legs.map((l) => `<li>${esc(l.outcome)}: ${cents(l.price)}</li>`).join("")}</ul>
      </div>`).join("")
    : empty("No arbitrage right now. These are rare and usually disappear within minutes.");

  $("#opps-flow").innerHTML = flow.length
    ? flow.map((o) => `
      <div class="card">
        <h3>${esc(o.title)}</h3>
        <p><b>${esc(o.reason)}</b></p>
        <p class="muted">${compact(o.recent_volume)} contracts across the last ${o.trades} trades · ${Math.round(o.yes_share * 100)}% bought YES</p>
        <button class="btn secondary" data-open="${esc(o.ticker)}">Details</button>
      </div>`).join("")
    : empty("Nothing unusual in the busiest markets right now.");
}

function renderCategories() {
  const sel = $("#category");
  const current = sel.value;
  const cats = [...new Set(state.markets.map((m) => m.category))].sort();
  sel.innerHTML = `<option value="">All categories</option>` + cats.map((c) => `<option ${c === current ? "selected" : ""}>${esc(c)}</option>`).join("");
}

function filteredMarkets() {
  const q = $("#search").value.trim().toLowerCase();
  const cat = $("#category").value;
  const sort = $("#sort").value;
  let list = state.markets.filter((m) => (!cat || m.category === cat) && (!q || `${m.title} ${m.ticker}`.toLowerCase().includes(q)));
  const key = {
    volume_24h: (m) => -m.volume_24h,
    volume: (m) => -m.volume,
    close: (m) => new Date(m.close_time || 8.64e15).getTime(),
    chance: (m) => -(m.chance ?? -1),
  }[sort];
  return list.sort((a, b) => key(a) - key(b));
}

function marketRow(m) {
  return `
    <button class="row" data-open="${esc(m.ticker)}">
      <span><span class="name">${esc(m.title)}</span><br><span class="sub">${esc(m.category)} · closes ${relTime(m.close_time, true)}${state.estimates[m.ticker] != null ? ` · <b>your pick ${pct(state.estimates[m.ticker])}</b>` : ""}</span></span>
      <span class="num chance">${pct(m.chance)}</span>
      <span class="num hide-sm">${tradable(m.yes_ask) ? cents(m.yes_ask) : "–"}</span>
      <span class="num hide-sm">${tradable(m.no_ask) ? cents(m.no_ask) : "–"}</span>
      <span class="num hide-sm">${compact(m.volume_24h)}</span>
    </button>`;
}

function renderMarkets() {
  const list = filteredMarkets();
  $("#count-markets").textContent = state.markets.length ? compact(state.markets.length) : "";
  $("#market-list").innerHTML = list.length
    ? list.slice(0, shown).map(marketRow).join("")
    : empty(state.markets.length ? "No markets match your search." : "Markets will appear here once they load.");
  $("#more").hidden = list.length <= shown;
  $("#more").textContent = `Show more (${(list.length - shown).toLocaleString()} left)`;
}

function renderPicks() {
  const tickers = Object.keys(state.estimates);
  $("#count-picks").textContent = tickers.length || "";
  $("#picks-list").innerHTML = tickers.length
    ? `<div class="table-head picks-row" aria-hidden="true"><span>Market</span><span>You say</span><span>Market says</span><span>Best trade</span></div>` +
      tickers.map((t) => {
        const m = state.byTicker[t];
        const yours = state.estimates[t];
        if (!m) return `<div class="row picks-row"><span><span class="name">${esc(t)}</span><br><span class="sub">No longer open</span></span><span class="num">${pct(yours)}</span><span></span><button class="btn secondary" data-remove="${esc(t)}">Remove</button></div>`;
        const r = evaluate(yours / 100, m);
        const best = [["YES", r.yes], ["NO", r.no]].filter(([, v]) => v).sort((a, b) => b[1].ev - a[1].ev)[0];
        const bestText = best ? `<span class="${best[1].ev > 0 ? "good" : "bad"}">${best[0]} ${signed(best[1].ev)}</span>` : "–";
        return `
          <button class="row picks-row" data-open="${esc(t)}">
            <span><span class="name">${esc(m.title)}</span><br><span class="sub">closes ${relTime(m.close_time, true)}</span></span>
            <span class="num chance">${pct(yours)}</span>
            <span class="num">${pct(m.chance)}</span>
            <span class="num">${bestText}</span>
          </button>`;
      }).join("")
    : empty("No picks yet. Open a market and enter your own chance to start tracking it.");
}

function renderSettings() {
  const form = $("#settings-form");
  if (form.contains(document.activeElement)) return; // don't overwrite while typing
  for (const [k, v] of Object.entries(state.settings)) if (form.elements[k]) form.elements[k].value = v;
}

// ---------- market dialog ----------
function openMarket(ticker) {
  const m = state.byTicker[ticker];
  if (!m) return;
  const saved = state.estimates[ticker];
  const start = saved ?? Math.round(m.chance ?? 50);
  const link = m.series_ticker ? `https://kalshi.com/markets/${encodeURIComponent(m.series_ticker.toLowerCase())}` : "https://kalshi.com";
  $("#dialog-body").innerHTML = `
    <h3>${esc(m.title)}</h3>
    <div class="muted">${esc(m.category)} · closes ${relTime(m.close_time, true)} · ${compact(m.volume)} traded</div>
    <div class="prices">
      <div><small>Market chance</small><b>${pct(m.chance)}</b></div>
      <div><small>Buy YES</small><b>${tradable(m.yes_ask) ? cents(m.yes_ask) : "–"}</b></div>
      <div><small>Buy NO</small><b>${tradable(m.no_ask) ? cents(m.no_ask) : "–"}</b></div>
    </div>
    <label for="est-num"><b>What do you think the chance of YES is?</b></label>
    <div class="estimate">
      <input id="est-range" type="range" min="1" max="99" step="1" value="${Math.min(99, Math.max(1, Math.round(start)))}">
      <input id="est-num" type="number" min="1" max="99" step="0.5" value="${start}"> %
    </div>
    <div id="est-results" class="results"></div>
    <div class="dialog-actions">
      <button id="est-save" class="btn">${saved != null ? "Update my pick" : "Save as my pick"}</button>
      ${saved != null ? `<button id="est-remove" class="btn secondary">Remove pick</button>` : ""}
      ${state.mode === "demo" ? "" : `<a class="btn secondary" href="${link}" target="_blank" rel="noopener">Open on Kalshi ↗</a>`}
    </div>
    ${m.rules ? `<p class="rules">${esc(m.rules)}</p>` : ""}`;

  const range = $("#est-range"), num = $("#est-num");
  const update = () => showResults(m, parseFloat(num.value));
  range.oninput = () => { num.value = range.value; update(); };
  num.oninput = () => { range.value = num.value; update(); };
  update();

  $("#est-save").onclick = async () => {
    const chance = parseFloat(num.value);
    if (!(chance > 0 && chance < 100)) return;
    await api("/api/estimate", { ticker, chance });
    $("#market-dialog").close();
    await load();
  };
  const rm = $("#est-remove");
  if (rm) rm.onclick = async () => { await api("/api/estimate", { ticker, chance: null }); $("#market-dialog").close(); await load(); };
  $("#market-dialog").showModal();
}

function showResults(m, chance) {
  const box = $("#est-results");
  if (!(chance > 0 && chance < 100)) { box.innerHTML = `<div>Enter a number between 1 and 99.</div><div></div>`; return; }
  const r = evaluate(chance / 100, m);
  const bankroll = state.settings.bankroll;
  const side = (name, v) => {
    if (!v) return `<div><small>Buy ${name}</small><b>Not available</b><small>No one is selling right now.</small></div>`;
    const stake = bankroll && v.ev > 0 ? `<br><small>Suggested stake: ${money(bankroll * v.kelly)}</small>` : "";
    return `<div class="${v.ev > 0 ? "pos" : ""}"><small>Buy ${name} at ${cents(v.price)}</small>
      <b class="${v.ev > 0 ? "good" : "bad"}">${signed(v.ev)}</b>
      <small>${v.ev > 0 ? "expected profit" : "expected loss"} per contract, after ${cents(v.cost - v.price)} fee</small>${stake}</div>`;
  };
  box.innerHTML = side("YES", r.yes) + side("NO", r.no) +
    (!bankroll ? `<small style="grid-column:1/-1">Tip: set a bankroll in Settings to see how much to bet.</small>` : "");
}

// ---------- events ----------
document.querySelectorAll(".tabs button").forEach((btn) => btn.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b === btn));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== `tab-${btn.dataset.tab}`));
}));

document.addEventListener("click", async (e) => {
  const open = e.target.closest("[data-open]");
  if (open) return openMarket(open.dataset.open);
  const remove = e.target.closest("[data-remove]");
  if (remove) { await api("/api/estimate", { ticker: remove.dataset.remove, chance: null }); await load(); }
});

let searchTimer;
$("#search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { shown = PAGE; renderMarkets(); }, 150); });
$("#category").addEventListener("change", () => { shown = PAGE; renderMarkets(); });
$("#sort").addEventListener("change", () => { shown = PAGE; renderMarkets(); });
$("#more").addEventListener("click", () => { shown += PAGE; renderMarkets(); });

$("#refresh").addEventListener("click", async () => {
  $("#refresh").disabled = true;
  $("#refresh").textContent = "Refreshing…";
  await api("/api/refresh", {});
  poll();
});

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const msg = $("#settings-saved");
  try {
    await api("/api/settings", {
      bankroll: +f.bankroll.value, min_edge_cents: +f.min_edge_cents.value, refresh_minutes: +f.refresh_minutes.value,
      large_trade: +f.large_trade.value, watch_series: f.watch_series.value, fee_rate: +f.fee_rate.value,
    });
    msg.textContent = "Saved ✓";
    document.activeElement.blur();
    await load();
  } catch (err) {
    msg.textContent = err.message;
  }
  setTimeout(() => (msg.textContent = ""), 3000);
});

load().catch(() => ($("#updated").textContent = "Could not reach the app"));
setInterval(poll, 4000);
