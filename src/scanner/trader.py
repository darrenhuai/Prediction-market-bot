"""Automatic trading, with the brakes on by default.

Modes (the ``auto_trade`` setting):

* ``off``   - never trades. The default.
* ``paper`` - records the trades it *would* make, at real prices, in
              ``data/trades.json``. Nothing is sent to Kalshi.
* ``live``  - places real orders. Also needs ``ALLOW_LIVE_TRADING=yes`` in
              ``.env``, so a stray click can't switch it on.

Sizing follows the 1% rule: each trade risks ``trade_fraction`` (default 1%)
of your current Kalshi balance. On top of that: a daily cap on money spent
and trades placed, one trade per opportunity per day, and no orders left
resting on the book (immediate-or-cancel / fill-or-kill only).

What it trades:

* Locked-in arbitrage: buy NO on every outcome of the set, fill-or-kill per
  leg. If a later leg fails, the earlier legs are ordinary NO positions,
  bought at their listed price; that is logged, and the set is not retried
  that day.
* Your picks: buy the side with an edge at its listed price.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("kalshi-bot")

MODES = ("off", "paper", "live")
MAX_LEDGER = 2000


def live_trading_allowed() -> bool:
    return os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() in ("yes", "true", "1")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Trader:
    def __init__(self, source: Any, ledger_path: Path):
        self.source = source
        self.ledger_path = ledger_path
        self.ledger: list[dict[str, Any]] = self._read()

    # ---- ledger ------------------------------------------------------
    def _read(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.ledger_path.read_text())
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.ledger_path.parent, prefix=".trades-", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(self.ledger[-MAX_LEDGER:], f, indent=1)
        os.replace(tmp, self.ledger_path)

    def _record(self, entry: dict[str, Any]) -> None:
        self.ledger.append({"time": _now(), **entry})
        self._save()

    def today(self) -> list[dict[str, Any]]:
        day = _now()[:10]
        return [t for t in self.ledger if t["time"][:10] == day]

    # ---- the rules ---------------------------------------------------
    def run(self, opportunities: dict[str, list[dict[str, Any]]], settings: dict[str, Any],
            balance: float | None) -> list[dict[str, Any]]:
        """Trade what the rules allow. Returns the ledger entries written this run."""
        mode = settings.get("auto_trade", "off")
        if mode == "off":
            return []
        if mode == "live" and not live_trading_allowed():
            log.warning("auto_trade is 'live' but ALLOW_LIVE_TRADING is not 'yes' in .env; trading on paper instead.")
            mode = "paper"
        if mode == "live" and not getattr(self.source, "has_auth", False):
            log.warning("auto_trade is 'live' but no Kalshi API key is configured; trading on paper instead.")
            mode = "paper"
        if balance is None or balance <= 0:
            log.warning("Auto-trade skipped: your balance is unknown, so the 1%% rule can't be applied.")
            return []

        self.ledger = self._read()  # the other process (bot or app) may have traded
        fraction = float(settings.get("trade_fraction", 0.01))
        per_trade = balance * fraction
        spent_today = sum(t.get("cost", 0.0) for t in self.today() if t.get("filled"))
        daily_budget = balance * float(settings.get("max_daily_fraction", 0.10))
        trades_today = len([t for t in self.today() if t.get("filled")])
        max_trades = int(settings.get("max_trades_per_day", 20))
        done_today = {t["key"] for t in self.today()}
        written = []

        candidates = [(o, "arbitrage") for o in opportunities.get("arbitrage", [])] + \
                     [(o, "pick") for o in opportunities.get("picks", [])]
        for opp, kind in candidates:
            if opp["key"] in done_today:
                continue
            if trades_today >= max_trades:
                log.info("Auto-trade: daily trade limit (%d) reached.", max_trades)
                break
            legs = self._legs(opp, kind, per_trade)
            if not legs:
                self._record({"mode": mode, "kind": kind, "key": opp["key"], "title": opp["title"], "legs": [],
                              "filled": False, "cost": 0.0,
                              "note": f"Skipped: 1% of your balance (${per_trade:.2f}) doesn't buy one contract"})
                done_today.add(opp["key"])
                continue
            planned_cost = sum(leg["contracts"] * leg["price"] / 100 for leg in legs)
            if spent_today + planned_cost > daily_budget:
                log.info("Auto-trade: daily spending cap ($%.2f) reached.", daily_budget)
                break
            entry = self._execute(mode, kind, opp, legs)
            written.append(entry)
            done_today.add(opp["key"])
            if entry["filled"]:
                spent_today += entry["cost"]
                trades_today += 1
        return written

    def _legs(self, opp: dict[str, Any], kind: str, per_trade_dollars: float) -> list[dict[str, Any]]:
        """Work out what to buy for one opportunity, sized to ``per_trade_dollars``."""
        if kind == "arbitrage":
            sets = math.floor(per_trade_dollars * 100 / opp["cost_cents"])
            if sets < 1:
                return []
            return [{"ticker": leg["ticker"], "buy": "NO", "contracts": sets, "price": leg["price"],
                     "outcome": leg["outcome"]} for leg in opp["legs"]]
        # pick: cost per contract is the ask plus fee; opp["price"] is the ask.
        from src.scanner.signals import single_contract_fee
        cost = opp["price"] + single_contract_fee(opp["price"])
        contracts = math.floor(per_trade_dollars * 100 / cost)
        if contracts < 1:
            return []
        return [{"ticker": opp["ticker"], "buy": opp["side"], "contracts": contracts, "price": opp["price"],
                 "outcome": opp["title"]}]

    def _execute(self, mode: str, kind: str, opp: dict[str, Any], legs: list[dict[str, Any]]) -> dict[str, Any]:
        entry: dict[str, Any] = {"mode": mode, "kind": kind, "key": opp["key"], "title": opp["title"],
                                 "legs": [], "filled": False, "cost": 0.0, "note": ""}
        # Arbitrage legs are all-or-nothing each (fill or kill); a pick takes what it can get.
        tif = "fill_or_kill" if kind == "arbitrage" else "immediate_or_cancel"
        for i, leg in enumerate(legs):
            done = dict(leg)
            if mode == "paper":
                done.update(filled=leg["contracts"], avg_price=leg["price"], order_id="paper")
            else:
                try:
                    resp = self.source.place_order(leg["ticker"], leg["buy"], leg["contracts"], leg["price"], tif)
                    filled = float(resp.get("fill_count") or 0)
                    avg = resp.get("average_fill_price")
                    # Kalshi reports the YES price; a NO buy cost 100 minus that.
                    avg_cents = float(avg) * 100 if avg is not None else leg["price"]
                    if leg["buy"] == "NO" and avg is not None:
                        avg_cents = 100 - avg_cents
                    done.update(filled=filled, avg_price=round(avg_cents, 2), order_id=resp.get("order_id", ""))
                except Exception as e:
                    done.update(filled=0, avg_price=None, order_id="", error=str(e)[:200])
                    log.warning("Order failed for %s: %s", leg["ticker"], e)
            entry["legs"].append(done)
            entry["cost"] += done["filled"] * (done.get("avg_price") or leg["price"]) / 100
            if done["filled"] < leg["contracts"] and kind == "arbitrage":
                unfilled = len(legs) - i - (1 if done["filled"] else 0)
                entry["note"] = (f"Stopped: leg {i + 1} of {len(legs)} did not fill, so this is not a complete set. "
                                 f"{unfilled} leg(s) were not bought.") if i or done["filled"] else \
                                "Nothing bought: the first leg did not fill at the listed price."
                break
        entry["filled"] = any(leg["filled"] for leg in entry["legs"])
        if kind == "arbitrage" and entry["filled"] and not entry["note"]:
            entry["note"] = f"Complete set x{legs[0]['contracts']}: locked in +{opp['profit_cents'] * legs[0]['contracts'] / 100:.2f} dollars"
        elif kind == "pick" and entry["filled"]:
            entry["note"] = f"Bought {entry['legs'][0]['filled']:g} x {opp['side']} at {entry['legs'][0]['avg_price']:g}c"
        elif not entry["filled"] and not entry["note"]:
            entry["note"] = "Nothing bought: the order did not fill at the listed price."
        entry["cost"] = round(entry["cost"], 2)
        self._record(entry)
        label = "PAPER TRADE" if mode == "paper" else "TRADE"
        log.info("%s: %s | %s | $%.2f | %s", label, kind, opp["title"], entry["cost"], entry["note"])
        return entry
