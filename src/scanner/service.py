"""The scanner: fetches markets, keeps your estimates and settings, and finds opportunities.

Everything it remembers lives in small JSON files under ``data/`` so both the
web app and the headless bot see the same picks and settings.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.scanner.alerts import Alerter
from src.scanner.markets import flatten_events, normalize_trade
from src.scanner.signals import find_arbitrage, find_pick_opportunities, flow_signal

log = logging.getLogger("kalshi-bot")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def default_settings() -> dict[str, Any]:
    return {
        # MIN_EV_THRESHOLD is in dollars per contract (0.02 = 2 cents), as in the original bot.
        "min_edge_cents": round(_env_float("MIN_EV_THRESHOLD", 0.02) * 100, 2),
        "bankroll": _env_float("BANKROLL", 0.0),
        "fee_rate": _env_float("KALSHI_FEE_RATE", 0.07),
        "refresh_minutes": max(1.0, _env_float("BOT_INTERVAL_SECONDS", 300) / 60),
        "large_trade": _env_float("LARGE_TRADE_THRESHOLD", 50),
        "flow_markets": 10,
        "max_event_pages": 50,
        "watch_series": os.getenv("WATCH_SERIES", ""),
    }


SETTING_TYPES = {k: type(v) for k, v in default_settings().items()}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Scanner:
    def __init__(self, source: Any, data_dir: Path = Path("data"), mode: str = "live"):
        self.source = source
        self.mode = mode
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        # Demo mode keeps its own files so pretend picks never mix with real ones.
        prefix = "demo_" if mode == "demo" else ""
        self._paths = {name: data_dir / f"{prefix}{name}.json" for name in ("settings", "estimates", "snapshot")}
        self.alerter = Alerter(data_dir / f"{prefix}alert_state.json")
        self._lock = threading.RLock()
        self._refreshing = threading.Lock()
        self.settings = {**default_settings(), **self._load("settings", {})}
        self.estimates: dict[str, float] = self._load("estimates", {})
        self.snapshot: dict[str, Any] = self._load("snapshot", {}) or {
            "updated_at": None, "markets": [], "events": [], "flow": [], "balance": None, "error": None,
        }
        self._index()

    # ---- persistence -------------------------------------------------
    def _load(self, name: str, default: Any) -> Any:
        try:
            return json.loads(self._paths[name].read_text())
        except (OSError, ValueError):
            return default

    def _save(self, name: str, value: Any) -> None:
        tmp = self._paths[name].with_suffix(".tmp")
        tmp.write_text(json.dumps(value, indent=1))
        tmp.replace(self._paths[name])

    def _index(self) -> None:
        self.by_ticker = {m["ticker"]: m for m in self.snapshot.get("markets", [])}

    # ---- refreshing --------------------------------------------------
    @property
    def is_refreshing(self) -> bool:
        return self._refreshing.locked()

    def refresh(self) -> bool:
        """Pull fresh markets, trade flow and balance. Returns False if a refresh was already running."""
        if not self._refreshing.acquire(blocking=False):
            return False
        try:
            s = self.settings
            try:
                raw_events = self.source.get_all_events(max_pages=int(s["max_event_pages"]))
            except Exception as e:
                log.warning("Market refresh failed: %s", e)
                with self._lock:
                    self.snapshot["error"] = f"Could not load markets from Kalshi: {e}"
                return True
            events, markets = flatten_events(raw_events)
            watch = [w.strip().upper() for w in s["watch_series"].split(",") if w.strip()]
            if watch:
                keep = {e["event_ticker"] for e in events if any(w in e["series_ticker"].upper() for w in watch)}
                events = [e for e in events if e["event_ticker"] in keep]
                markets = [m for m in markets if m["event_ticker"] in keep]

            flow = []
            busiest = sorted(markets, key=lambda m: m["volume_24h"], reverse=True)[: int(s["flow_markets"])]
            for m in busiest:
                try:
                    trades = [normalize_trade(t) for t in self.source.get_trades(ticker=m["ticker"], limit=100).get("trades") or []]
                except Exception as e:
                    log.debug("Trades for %s failed: %s", m["ticker"], e)
                    continue
                sig = flow_signal(m["ticker"], trades, large_trade=s["large_trade"])
                if sig:
                    flow.append({**sig, "title": m["title"]})

            balance = None
            try:
                balance = self.source.get_balance().get("balance") / 100
            except Exception:
                pass  # no credentials configured; balance is optional

            with self._lock:
                self.snapshot = {"updated_at": now_iso(), "markets": markets, "events": events, "flow": flow,
                                 "balance": balance, "error": None}
                self._index()
                self._save("snapshot", self.snapshot)
            log.info("Refreshed %d markets in %d events", len(markets), len(events))
            return True
        finally:
            self._refreshing.release()

    # ---- analysis ----------------------------------------------------
    def opportunities(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            s = self.settings
            return {
                "picks": find_pick_opportunities(self.by_ticker, self.estimates, s["min_edge_cents"],
                                                 s["fee_rate"], s["bankroll"]),
                "arbitrage": find_arbitrage(self.snapshot.get("events", []), self.by_ticker, s["fee_rate"]),
                "flow": list(self.snapshot.get("flow", [])),
            }

    def all_opportunities(self) -> list[dict[str, Any]]:
        return [o for group in self.opportunities().values() for o in group]

    # ---- user input --------------------------------------------------
    def set_estimate(self, ticker: str, chance_percent: float | None) -> None:
        with self._lock:
            if chance_percent is None:
                self.estimates.pop(ticker, None)
            else:
                if not 0 < chance_percent < 100:
                    raise ValueError("Chance must be between 0 and 100")
                self.estimates[ticker] = round(chance_percent / 100, 4)
            self._save("estimates", self.estimates)

    def update_settings(self, changes: dict[str, Any]) -> None:
        with self._lock:
            for key, value in changes.items():
                if key not in SETTING_TYPES:
                    raise ValueError(f"Unknown setting: {key}")
                value = SETTING_TYPES[key](value)
                if isinstance(value, float) and value < 0:
                    raise ValueError(f"{key} can't be negative")
                self.settings[key] = value
            self.settings["refresh_minutes"] = max(1.0, self.settings["refresh_minutes"])
            self._save("settings", self.settings)

    def state(self) -> dict[str, Any]:
        """Everything the web UI needs in one payload."""
        with self._lock:
            return {
                "mode": self.mode,
                "refreshing": self.is_refreshing,
                "updated_at": self.snapshot.get("updated_at"),
                "error": self.snapshot.get("error"),
                "balance": self.snapshot.get("balance"),
                "settings": self.settings,
                "estimates": {t: round(p * 100, 2) for t, p in self.estimates.items()},
                "markets": self.snapshot.get("markets", []),
                "opportunities": self.opportunities(),
            }
