"""The scanner: fetches markets, keeps your estimates and settings, and finds opportunities.

Everything it remembers lives in small JSON files under ``data/`` so both the
web app and the headless bot see the same picks and settings. Both re-read
those files on every refresh, so they can run at the same time.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

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
# Inclusive (min, max) for each number setting, so a typo can't hammer Kalshi or break the app.
SETTING_BOUNDS: dict[str, tuple[float, float]] = {
    "min_edge_cents": (0, 100),
    "bankroll": (0, 1e12),
    "fee_rate": (0, 0.5),
    "refresh_minutes": (1, 24 * 60),
    "large_trade": (1, 1e9),
    "flow_markets": (0, 100),
    "max_event_pages": (1, 500),
}
MAX_TEXT_SETTING = 500


def validate_setting(key: str, value: Any) -> Any:
    """Coerce ``value`` to the setting's type and check it's in range. Raises ValueError."""
    if key not in SETTING_TYPES:
        raise ValueError(f"Unknown setting: {key}")
    kind = SETTING_TYPES[key]
    if kind is str:
        value = str(value)
        if len(value) > MAX_TEXT_SETTING:
            raise ValueError(f"{key} is too long")
        return value
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as e:
        raise ValueError(f"{key} must be a number") from e
    lo, hi = SETTING_BOUNDS[key]
    if not math.isfinite(number) or not lo <= number <= hi:
        raise ValueError(f"{key} must be between {lo:g} and {hi:g}")
    return int(number) if kind is int else number


def friendly_error(e: Exception) -> str:
    """A short, plain description of why talking to Kalshi failed."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        meaning = {401: "your API key was rejected", 403: "access was refused", 404: "not found",
                   429: "too many requests"}.get(code, "server error" if code >= 500 else "request refused")
        return f"Kalshi answered {code} ({meaning})"
    if isinstance(e, httpx.TransportError):
        return "Couldn't reach Kalshi (no internet connection, a blocked network, or Kalshi is down)"
    return str(e) or type(e).__name__


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
        # Values set at runtime that beat saved settings, e.g. bot.py --min-ev.
        self.overrides: dict[str, Any] = {}
        self.reload()
        self.snapshot: dict[str, Any] = self._load("snapshot", {}) or {
            "updated_at": None, "markets": [], "events": [], "flow": [], "balance": None, "error": None,
        }
        self._index()

    def reload(self) -> None:
        """Re-read picks and settings, which the other process (bot or web app) may have changed.

        Only settings changed in the app are saved, so anything else keeps
        following its .env default.
        """
        saved = self._load("settings", {})
        settings = default_settings()
        for key, value in saved.items() if isinstance(saved, dict) else ():
            try:
                settings[key] = validate_setting(key, value)
            except ValueError as e:
                log.warning("Ignoring saved setting %s=%r: %s", key, value, e)
        estimates = self._load("estimates", {})
        with self._lock:
            self._saved_settings = {k: v for k, v in saved.items() if k in settings} if isinstance(saved, dict) else {}
            self.settings = {**settings, **self.overrides}
            self.estimates = {t: p for t, p in estimates.items() if isinstance(p, (int, float)) and 0 < p < 1} \
                if isinstance(estimates, dict) else {}

    # ---- persistence -------------------------------------------------
    def _load(self, name: str, default: Any) -> Any:
        path = self._paths[name]
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return default
        except (OSError, ValueError) as e:
            log.warning("Could not read %s (%s); starting from empty", path, e)
            return default

    def _save(self, name: str, value: Any) -> None:
        # A unique temp file per write, then an atomic rename, so the bot and
        # the web app can both save without clobbering each other's files.
        path = self._paths[name]
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(value, f, indent=None if name == "snapshot" else 1, allow_nan=False)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

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
            self.reload()
            s = self.settings
            try:
                raw_events = self.source.get_all_events(max_pages=int(s["max_event_pages"]))
            except Exception as e:
                log.warning("Market refresh failed: %s", e)
                with self._lock:
                    self.snapshot["error"] = friendly_error(e)
                    self.snapshot["offline"] = isinstance(e, httpx.TransportError)
                return True
            events, markets = flatten_events(raw_events, self._series_categories())
            watch = [w.strip().upper() for w in s["watch_series"].split(",") if w.strip()]
            if watch:
                keep = {e["event_ticker"] for e in events if any(w in e["series_ticker"].upper() for w in watch)}
                events = [e for e in events if e["event_ticker"] in keep]
                # Markets you've saved a pick on stay in, so your picks are always checked.
                markets = [m for m in markets if m["event_ticker"] in keep or m["ticker"] in self.estimates]

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

            balance, balance_error = None, None
            if getattr(self.source, "has_auth", True):  # skip quietly when no API key is configured
                try:
                    raw = self.source.get_balance()
                    dollars = raw.get("balance_dollars")
                    balance = float(dollars) if dollars is not None else raw["balance"] / 100
                except Exception as e:
                    log.warning("Could not load your Kalshi balance: %s", e)
                    balance_error = friendly_error(e)

            with self._lock:
                self.snapshot = {"updated_at": now_iso(), "markets": markets, "events": events, "flow": flow,
                                 "balance": balance, "balance_error": balance_error, "error": None,
                                 "truncated": bool(getattr(self.source, "events_truncated", False))}
                self._index()
                self._save("snapshot", self.snapshot)
            log.info("Refreshed %d markets in %d events", len(markets), len(events))
            return True
        finally:
            self._refreshing.release()

    def _series_categories(self) -> dict[str, str]:
        """Series ticker -> category. Optional: an empty map just means "Other" everywhere."""
        get_series = getattr(self.source, "get_series_list", None)
        if get_series is None:
            return {}
        try:
            return {s["ticker"]: s.get("category") or "Other" for s in get_series() if s.get("ticker")}
        except Exception as e:
            log.warning("Could not load market categories: %s", e)
            return {}

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
        if not ticker or len(ticker) > 200:
            raise ValueError("Unknown market")
        with self._lock:
            estimates = self._load("estimates", {})  # merge with the other process's picks
            self.estimates = estimates if isinstance(estimates, dict) else {}
            if chance_percent is None:
                self.estimates.pop(ticker, None)
            else:
                if not (math.isfinite(chance_percent) and 0 < chance_percent < 100):
                    raise ValueError("Chance must be between 0 and 100")
                if ticker not in self.by_ticker and ticker not in self.estimates:
                    raise ValueError("Unknown market")
                self.estimates[ticker] = round(chance_percent / 100, 4)
            self._save("estimates", self.estimates)

    def update_settings(self, changes: dict[str, Any]) -> None:
        """Validate and save settings. Nothing is saved if any value is invalid."""
        checked = {key: validate_setting(key, value) for key, value in changes.items()}
        with self._lock:
            saved = self._load("settings", {})
            saved = {k: v for k, v in saved.items() if k in SETTING_TYPES} if isinstance(saved, dict) else {}
            defaults = default_settings()
            for key, value in checked.items():
                if value == defaults[key]:
                    saved.pop(key, None)  # back to following .env
                else:
                    saved[key] = value
            self._save("settings", saved)
        self.reload()

    def market(self, ticker: str) -> dict[str, Any] | None:
        with self._lock:
            return self.by_ticker.get(ticker)

    def markets(self) -> list[dict[str, Any]]:
        """Every market for the list view, minus the long rules text (the detail view fetches that)."""
        with self._lock:
            return [{k: v for k, v in m.items() if k != "rules"} for m in self.snapshot.get("markets", [])]

    def state(self) -> dict[str, Any]:
        """Everything the web UI needs except the market list, which is fetched separately when it changes."""
        with self._lock:
            return {
                "mode": self.mode,
                "refreshing": self.is_refreshing,
                "updated_at": self.snapshot.get("updated_at"),
                "error": self.snapshot.get("error"),
                "offline": bool(self.snapshot.get("offline")),
                "truncated": bool(self.snapshot.get("truncated")),
                "balance": self.snapshot.get("balance"),
                "balance_error": self.snapshot.get("balance_error"),
                "market_count": len(self.snapshot.get("markets", [])),
                "settings": self.settings,
                "saved_settings": sorted(self._saved_settings),
                "estimates": {t: round(p * 100, 2) for t, p in self.estimates.items()},
                "opportunities": self.opportunities(),
            }
