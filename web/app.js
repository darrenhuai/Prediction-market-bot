// Prediction Market Bot UI. Plain JavaScript, no build step.
const $ = (sel) => document.querySelector(sel);
const PAGE = 60;
// Empty placeholder so everything can render before the first load finishes.
let state = { markets: [], byTicker: {}, estimates: {}, settings: {}, saved_settings: [], market_count: 0,
  opportunities: { picks: [], arbitrage: [], flow: [] } };
let markets = { updated_at: undefined, list: [] };
let loaded = false;
let shown = PAGE;
let loading = null;
let settingsDirty = false;

// ---------- formatting ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const cents = (c) => (c == null ? "–" : `${+c.toFixed(1)}¢`);
const signed = (c) => `${c >= 0 ? "+" : "−"}${Math.abs(c).toFixed(1)}¢`;
const pct = (p) => (p == null ? "–" : `${Math.round(p)}%`);
const money = (d) => `$${d.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: d < 100 ? 2 : 0 })}`;
const compact = (n) => (n ? Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n) : "0");
const tradable = (p) => p != null && p > 0 && p < 100;
const lbl = (text) => `<span class="lbl">${text} </span>`; // column name, shown on phones and to screen readers

function relTime(iso) {
  if (!iso) return "";
  const diff = (new Date(iso) - Date.now()) / 1000;
  if (Number.isNaN(diff)) return "";
  const a = Math.abs(diff);
  if (a < 60) return "just now";
  let n = Math.round(a / 60), unit = "min";
  if (n >= 60) { n = Math.round(a / 3600); unit = "hr"; }
  if (unit === "hr" && n >= 24) { n = Math.round(a / 86400); unit = "day"; }
  const label = `${n} ${unit}${n > 1 && unit !== "min" ? "s" : ""}`;
  return diff > 0 ? `in ${label}` : `${label} ago`;
}
function closes(iso) {
  const t = relTime(iso);
  if (!t) return "";
  return t.startsWith("in ") || t === "just now" ? `closes ${t}` : `closed ${t}`;
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

// One load at a time; the market list is only downloaded when it has changed.
function load() {
  loading ??= (async () => {
    const next = await api("/api/state");
    if (next.updated_at !== markets.updated_at) {
      const m = await api("/api/markets");
      markets = { updated_at: m.updated_at, list: m.markets };
    }
    state = { ...next, markets: markets.list, byTicker: Object.fromEntries(markets.list.map((m) => [m.ticker, m])) };
    loaded = true;
    render();
  })().finally(() => { loading = null; });
  return loading;
}

async function poll() {
  if (loading) return;
  try {
    const s = await api("/api/status");
    $("#refresh").disabled = s.refreshing;
    $("#refresh").textContent = s.refreshing ? "Refreshing…" : "Refresh";
    if (!loaded || s.updated_at !== state.updated_at || (s.error || null) !== (state.error || null)) await load();
    else renderStatus();
  } catch {
    $("#updated").textContent = "Can't reach the app. Is it still running?";
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
  const count = `${state.market_count.toLocaleString()} markets${state.truncated ? " (not all of them: raise the page limit to see more)" : ""}`;
  $("#updated").textContent = state.updated_at ? `Updated ${relTime(state.updated_at)} · ${count}` : state.error ? "No market data yet" : "Loading markets…";
  $("#balance").textContent = state.balance != null ? `Balance ${money(state.balance)}` : state.balance_error ? "Balance unavailable" : "";
  $("#balance").title = state.balance_error ? `Couldn't load your balance: ${state.balance_error}` : "";
  const err = $("#error");
  err.hidden = !state.error;
  if (state.error) {
    const mins = Math.round(state.settings.refresh_minutes);
    err.textContent = [
      `Couldn't load markets. ${state.error}.`,
      state.market_count ? "Showing the last data we had." : "",
      state.offline ? "Check your internet connection." : "",
      `The app will try again in ${mins} minute${mins === 1 ? "" : "s"}, or press Refresh.`,
    ].filter(Boolean).join(" ");
  }
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
        <p class="big good">${signed(o.ev_cents)} <small>expected per contract</small></p>
        <p>Buy ${o.side} at <b>${cents(o.price)}</b>. You think YES has a ${pct(o.your_chance)} chance; the price implies ${pct(o.market_chance)}.</p>
        ${o.suggested_stake ? `<p>Suggested stake: <b>${money(o.suggested_stake)}</b> (${o.contracts} contracts). <small>Only right if your chance is right.</small></p>` : ""}
        <button class="btn secondary" data-open="${esc(o.ticker)}">Details</button>
      </div>`).join("")
    : empty(Object.keys(state.estimates).length
      ? "None of your picks is a good buy at today's prices. The app keeps checking."
      : "You haven't added any picks yet. Open the <b>Markets</b> tab, tap a market, and enter the chance you think it has.");

  $("#opps-arbitrage").innerHTML = arbitrage.length
    ? arbitrage.map((o) => `
      <div class="card">
        <span class="tag ${o.guaranteed ? "good" : "warn"}">${o.guaranteed ? "Locked in" : "Not guaranteed"}</span>
        <h3>${esc(o.title)}</h3>
        <p class="big ${o.guaranteed ? "good" : ""}">${signed(o.profit_cents)} <small>per set${o.guaranteed ? "" : ", if it pays"}</small></p>
        <p>Buy <b>${o.side}</b> on all ${o.legs.length} outcomes, one of each, for ${cents(o.cost_cents)} with fees.
        ${o.guaranteed
          ? `Only one outcome can happen, so at least ${o.legs.length - 1} of them pay $1: you get back at least ${cents(o.payout_cents)} whatever happens.`
          : `Pays ${cents(o.payout_cents)} if one of these outcomes wins, but <b>nothing</b> if something not on this list happens.`}</p>
        <ul class="legs">${o.legs.map((l) => `<li>${esc(l.outcome)}: ${cents(l.price)}</li>`).join("")}</ul>
      </div>`).join("")
    : empty("None right now. These are rare and usually disappear within minutes.");

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
  const list = state.markets.filter((m) => (!cat || m.category === cat) && (!q || `${m.title} ${m.ticker}`.toLowerCase().includes(q)));
  const closeTime = (m) => { const t = new Date(m.close_time).getTime(); return Number.isNaN(t) ? Infinity : t; };
  const key = {
    volume_24h: (m) => -m.volume_24h,
    volume: (m) => -m.volume,
    close: closeTime,
    chance: (m) => -(m.chance ?? -1),
  }[sort];
  return list.sort((a, b) => key(a) - key(b));
}

function marketRow(m) {
  const pick = state.estimates[m.ticker];
  return `
    <button class="row" data-open="${esc(m.ticker)}">
      <span><span class="name">${esc(m.title)}</span><br><span class="sub">${esc(m.category)}${m.close_time ? ` · ${closes(m.close_time)}` : ""}${pick != null ? ` · <b>your pick ${pct(pick)}</b>` : ""}</span></span>
      <span class="num chance">${lbl("Chance")}${pct(m.chance)}</span>
      <span class="num hide-sm">${lbl("Buy Yes")}${tradable(m.yes_ask) ? cents(m.yes_ask) : "–"}</span>
      <span class="num hide-sm">${lbl("Buy No")}${tradable(m.no_ask) ? cents(m.no_ask) : "–"}</span>
      <span class="num hide-sm">${lbl("Traded (24h)")}${compact(m.volume_24h)}</span>
    </button>`;
}

function renderMarkets() {
  const list = filteredMarkets();
  $("#count-markets").textContent = state.market_count ? compact(state.market_count) : "";
  $("#market-list").innerHTML = list.length
    ? list.slice(0, shown).map(marketRow).join("")
    : empty(state.markets.length ? "No markets match your search." : "Markets will appear here once they load.");
  $("#more").hidden = list.length <= shown;
  $("#more").textContent = `Show more (${Math.max(0, list.length - shown).toLocaleString()} left)`;
}

function renderPicks() {
  const tickers = Object.keys(state.estimates);
  $("#count-picks").textContent = tickers.length || "";
  const missing = state.markets.length ? "No longer open" : "Markets not loaded yet";
  $("#picks-list").innerHTML = tickers.length
    ? `<div class="table-head picks-row" aria-hidden="true"><span>Market</span><span>You say</span><span>Price says</span><span>Best buy</span></div>` +
      tickers.map((t) => {
        const m = state.byTicker[t];
        const yours = state.estimates[t];
        if (!m) return `<div class="row picks-row"><span><span class="name">${esc(t)}</span><br><span class="sub">${missing}</span></span><span class="num">${lbl("You say")}${pct(yours)}</span><span></span><button class="btn secondary" data-remove="${esc(t)}">Remove</button></div>`;
        const r = evaluate(yours / 100, m);
        const best = [["YES", r.yes], ["NO", r.no]].filter(([, v]) => v).sort((a, b) => b[1].ev - a[1].ev)[0];
        const bestText = best ? `<span class="${best[1].ev > 0 ? "good" : "bad"}">${best[0]} ${signed(best[1].ev)}</span>` : "–";
        return `
          <button class="row picks-row" data-open="${esc(t)}">
            <span><span class="name">${esc(m.title)}</span><br><span class="sub">${closes(m.close_time)}</span></span>
            <span class="num chance">${lbl("You say")}${pct(yours)}</span>
            <span class="num">${lbl("Price says")}${pct(m.chance)}</span>
            <span class="num">${lbl("Best buy")}${bestText}</span>
          </button>`;
      }).join("")
    : empty("No picks yet. Open a market and enter your own chance to start tracking it.");
}

function renderSettings() {
  const form = $("#settings-form");
  if (settingsDirty || form.contains(document.activeElement)) return; // don't overwrite unsaved edits
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
    <div class="muted">${esc(m.category)}${m.close_time ? ` · ${closes(m.close_time)}` : ""} · ${compact(m.volume_24h)} contracts traded in the last 24h</div>
    <div class="prices">
      <div><small>Price implies</small><b>${pct(m.chance)}</b></div>
      <div><small>Buy YES for</small><b>${tradable(m.yes_ask) ? cents(m.yes_ask) : "–"}</b></div>
      <div><small>Buy NO for</small><b>${tradable(m.no_ask) ? cents(m.no_ask) : "–"}</b></div>
    </div>
    <p class="explain">Each contract pays <b>$1</b> if you're right and nothing if you're wrong. A YES price of 40¢ means traders put the chance at about 40%.</p>
    <label for="est-num"><b>What do you think the chance of YES is?</b></label>
    <div class="estimate">
      <input id="est-range" type="range" min="1" max="99" step="1" value="${Math.min(99, Math.max(1, Math.round(start)))}" aria-label="Your chance of YES">
      <input id="est-num" type="number" min="1" max="99" step="any" value="${start}"> %
    </div>
    <div id="est-results" class="results"></div>
    <div class="dialog-actions">
      <button id="est-save" class="btn">${saved != null ? "Update my pick" : "Save as my pick"}</button>
      ${saved != null ? `<button id="est-remove" class="btn secondary">Remove pick</button>` : ""}
      ${state.mode === "demo" ? "" : `<a class="btn secondary" href="${link}" target="_blank" rel="noopener">Open on Kalshi ↗</a>`}
    </div>
    <p id="est-error" class="bad" hidden></p>
    <p id="rules" class="rules"></p>`;

  const range = $("#est-range"), num = $("#est-num");
  const update = () => showResults(m, parseFloat(num.value));
  range.oninput = () => { num.value = range.value; update(); };
  num.oninput = () => { range.value = num.value; update(); };
  update();

  const save = async (chance) => {
    try {
      await api("/api/estimate", { ticker, chance });
      $("#market-dialog").close();
      await load();
    } catch (err) {
      $("#est-error").textContent = err.message;
      $("#est-error").hidden = false;
    }
  };
  $("#est-save").onclick = () => {
    const chance = parseFloat(num.value);
    if (chance > 0 && chance < 100) save(chance);
  };
  const rm = $("#est-remove");
  if (rm) rm.onclick = () => save(null);
  $("#market-dialog").showModal();

  // The rules text isn't in the market list (it's long), so fetch it for this market.
  api(`/api/market?ticker=${encodeURIComponent(ticker)}`)
    .then((full) => { if ($("#rules")) $("#rules").textContent = full.rules || ""; })
    .catch(() => {});
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
      <small>average ${v.ev > 0 ? "profit" : "loss"} per contract if your chance is right, after the ${cents(v.cost - v.price)} fee</small>${stake}</div>`;
  };
  box.innerHTML = side("YES", r.yes) + side("NO", r.no) +
    (!bankroll ? `<small class="span-all">Tip: set a bankroll in Settings to see how much to bet.</small>`
      : `<small class="span-all">Suggested stakes bet a small, careful share of your bankroll. They assume your chance is right, so bet less if you're unsure.</small>`);
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
  if (remove) {
    try { await api("/api/estimate", { ticker: remove.dataset.remove, chance: null }); } catch {}
    await load();
  }
});

let searchTimer;
$("#search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { shown = PAGE; renderMarkets(); }, 150); });
$("#category").addEventListener("change", () => { shown = PAGE; renderMarkets(); });
$("#sort").addEventListener("change", () => { shown = PAGE; renderMarkets(); });
$("#more").addEventListener("click", () => { shown += PAGE; renderMarkets(); });

$("#refresh").addEventListener("click", async () => {
  $("#refresh").disabled = true;
  $("#refresh").textContent = "Refreshing…";
  try { await api("/api/refresh", {}); } catch {}
  poll();
});

const form = $("#settings-form");
form.addEventListener("input", () => { settingsDirty = true; });
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = form.elements;
  const msg = $("#settings-saved");
  // Send only what changed, so settings you never touched keep following .env.
  const changes = {};
  for (const name of ["bankroll", "min_edge_cents", "refresh_minutes", "large_trade", "fee_rate"]) {
    const v = f[name].valueAsNumber;
    if (!Number.isFinite(v)) { msg.textContent = "Please fill in every number."; return; }
    if (v !== state.settings[name]) changes[name] = v;
  }
  if (f.watch_series.value !== state.settings.watch_series) changes.watch_series = f.watch_series.value;
  try {
    if (Object.keys(changes).length) await api("/api/settings", changes);
    settingsDirty = false;
    msg.textContent = "Saved ✓";
    document.activeElement.blur();
    await load();
  } catch (err) {
    msg.textContent = err.message;
  }
  setTimeout(() => (msg.textContent = ""), 4000);
});

render();
load().catch(() => ($("#updated").textContent = "Can't reach the app. Is it still running?"));
setInterval(poll, 4000);
