"""Opportunity detection.

A market's own prices can't tell you it is mispriced: any "fair value" built
from its bid/ask is always at or below what it costs to buy. So the scanner
only looks for three things that can actually point to an edge:

* **Your picks** - you enter the chance you think an outcome has, and the
  scanner flags when the price lets you buy YES or NO with positive expected
  value after fees.
* **Arbitrage** - in an event whose outcomes are mutually exclusive (at most
  one can happen), buying NO on every outcome pays at least ``N - 1`` dollars.
  If the whole bundle costs less than that, the profit is locked in.
* **Unusual activity** - heavy one-sided taker buying or very large trades.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any

from src.scanner.markets import is_tradable

DEFAULT_FEE_RATE = 0.07  # Kalshi's standard taker fee: rate * P * (1 - P) per contract


def taker_fee(price_cents: float, rate: float = DEFAULT_FEE_RATE) -> float:
    """Approximate Kalshi taker fee, in cents, for one contract bought at ``price_cents``.

    Kalshi charges ``rate * count * P * (1 - P)`` dollars per order, rounded
    up to the next cent, so the real fee on a tiny order is a little higher;
    for sizing decisions the unrounded per-contract figure is the fairer estimate.
    """
    p = price_cents / 100
    return rate * p * (1 - p) * 100


def single_contract_fee(price_cents: float, rate: float = DEFAULT_FEE_RATE) -> float:
    """Kalshi's actual fee, in whole cents, for an order of one contract (the per-order cent is rounded up)."""
    return float(math.ceil(round(taker_fee(price_cents, rate), 6)))


def evaluate_pick(prob: float, market: dict[str, Any], fee_rate: float = DEFAULT_FEE_RATE,
                  kelly_share: float = 0.25) -> dict[str, Any]:
    """Expected value of buying YES and NO given your probability ``prob`` (0-1) that YES wins.

    Returns per-contract EV in cents (after fees) for each side, the better
    side, and a fractional-Kelly bankroll share for it.
    """
    sides = {}
    for side, win_prob, ask in (("YES", prob, market.get("yes_ask")), ("NO", 1 - prob, market.get("no_ask"))):
        if not is_tradable(ask):
            sides[side] = None
            continue
        cost = ask + taker_fee(ask, fee_rate)
        ev = win_prob * 100 - cost
        # Kelly for a contract that costs `cost` and pays 100: f* = (p - c) / (1 - c)
        kelly = (win_prob - cost / 100) / (1 - cost / 100) if cost < 100 else 0.0
        sides[side] = {
            "price": ask,
            "cost": round(cost, 2),
            "ev_cents": round(ev, 2),
            "roi": round(ev / cost, 4) if cost else 0.0,
            "kelly": round(max(0.0, kelly) * kelly_share, 4),
        }
    candidates = [(s, v) for s, v in sides.items() if v is not None]
    best_side, best = max(candidates, key=lambda sv: sv[1]["ev_cents"]) if candidates else (None, None)
    return {"yes": sides["YES"], "no": sides["NO"], "best_side": best_side, "best": best}


def find_pick_opportunities(markets_by_ticker: dict[str, dict[str, Any]], estimates: dict[str, float],
                            min_edge_cents: float, fee_rate: float = DEFAULT_FEE_RATE,
                            bankroll: float = 0.0) -> list[dict[str, Any]]:
    opps = []
    for ticker, prob in estimates.items():
        market = markets_by_ticker.get(ticker)
        if market is None:
            continue
        result = evaluate_pick(prob, market, fee_rate)
        best = result["best"]
        if best is None or best["ev_cents"] < min_edge_cents:
            continue
        stake = bankroll * best["kelly"] if bankroll else 0.0
        opps.append({
            "kind": "pick",
            "key": f"pick:{ticker}:{result['best_side']}",
            "ticker": ticker,
            "title": market["title"],
            "side": result["best_side"],
            "price": best["price"],
            "your_chance": round(prob * 100, 1),
            "market_chance": market.get("chance"),
            "ev_cents": best["ev_cents"],
            "roi": best["roi"],
            "kelly": best["kelly"],
            "suggested_stake": round(stake, 2),
            "contracts": int(stake * 100 // best["cost"]) if stake else 0,
        })
    return sorted(opps, key=lambda o: o["ev_cents"], reverse=True)


def find_arbitrage(events: list[dict[str, Any]], markets_by_ticker: dict[str, dict[str, Any]],
                   fee_rate: float = DEFAULT_FEE_RATE, min_profit_cents: float = 0.5) -> list[dict[str, Any]]:
    """Look for mutually exclusive events whose outcome bundle is priced below its guaranteed payout.

    Costs use the fee Kalshi actually charges on a one-contract order (rounded
    up to the next cent), the worst case: buying more of each only lowers
    the fee per bundle, so a bundle that profits here profits at any size.
    """
    opps = []
    for ev in events:
        if not ev.get("mutually_exclusive"):
            continue
        markets = [markets_by_ticker[t] for t in ev.get("open_tickers", []) if t in markets_by_ticker]
        if len(markets) < 2:
            continue

        # Buy NO on every outcome: at most one outcome wins, so at least N-1 NOs pay $1.
        if all(is_tradable(m["no_ask"]) for m in markets):
            cost = sum(m["no_ask"] + single_contract_fee(m["no_ask"], fee_rate) for m in markets)
            payout = (len(markets) - 1) * 100
            if payout - cost >= min_profit_cents:
                opps.append(_arb(ev, markets, "NO", cost, payout, guaranteed=True))

        # Buy YES on every outcome: pays $1 if one of the listed outcomes wins, else nothing.
        # `complete` only rules out a closed market being the winner; Kalshi's
        # mutually_exclusive flag means "at most one YES", not "exactly one", so an
        # unlisted outcome can still win. That's why this bundle is never `guaranteed`.
        complete = len(markets) == ev.get("market_count")
        if complete and all(is_tradable(m["yes_ask"]) for m in markets):
            cost = sum(m["yes_ask"] + single_contract_fee(m["yes_ask"], fee_rate) for m in markets)
            if 100 - cost >= min_profit_cents:
                opps.append(_arb(ev, markets, "YES", cost, 100, guaranteed=False))
    return sorted(opps, key=lambda o: o["profit_cents"], reverse=True)


def _arb(ev, markets, side, cost, payout, guaranteed):
    return {
        "kind": "arbitrage",
        "key": f"arb:{ev['event_ticker']}:{side}",
        "event_ticker": ev["event_ticker"],
        "title": ev["title"],
        "side": side,
        "legs": [{"ticker": m["ticker"], "outcome": m["outcome"] or m["title"],
                  "price": m["no_ask"] if side == "NO" else m["yes_ask"]} for m in markets],
        "cost_cents": round(cost, 2),
        "payout_cents": payout,
        "profit_cents": round(payout - cost, 2),
        "guaranteed": guaranteed,
    }


LARGE_VS_TYPICAL = 20  # a trade counts as "large" only if it is this many times the market's typical trade


def flow_signal(ticker: str, trades: list[dict[str, Any]], large_trade: float = 50,
                min_trades: int = 10) -> dict[str, Any] | None:
    """Flag a trade far bigger than usual for this market, or lopsided taker buying (>80% one side).

    A trade is "large" if it is at least ``large_trade`` contracts *and* at
    least 20x the median trade here, so busy markets where 50-lots are
    routine don't fire on every scan. It is checked first because one huge
    trade also makes the volume look one-sided, and "one big trade" is the
    more accurate description of that.
    """
    if len(trades) < min_trades:
        return None
    yes_vol = sum(t["count"] for t in trades if t["taker_side"] == "yes")
    no_vol = sum(t["count"] for t in trades if t["taker_side"] == "no")
    total = yes_vol + no_vol
    if total == 0:
        return None
    yes_share = yes_vol / total
    typical = median(t["count"] for t in trades)
    biggest = max(trades, key=lambda t: t["count"])
    if biggest["count"] >= max(large_trade, LARGE_VS_TYPICAL * typical):
        reason = (f"Large trade: {int(biggest['count']):,} contracts bought on {biggest['taker_side'].upper() or '?'} "
                  f"(a typical trade here is {typical:,.0f})")
        kind = "large"
    elif yes_share > 0.8:
        reason = f"Heavy YES buying: {yes_share:.0%} of recent volume"
        kind = "yes"
    elif yes_share < 0.2:
        reason = f"Heavy NO buying: {1 - yes_share:.0%} of recent volume"
        kind = "no"
    else:
        return None
    return {
        "kind": "flow",
        "key": f"flow:{ticker}:{kind}",
        "ticker": ticker,
        "reason": reason,
        "yes_share": round(yes_share, 3),
        "recent_volume": total,
        "trades": len(trades),
    }
