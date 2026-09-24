"""Turn raw Kalshi API market/event/trade dicts into one simple, consistent shape.

Kalshi has been migrating its API from integer-cent fields (``yes_bid: 42``)
to fixed-point string fields (``yes_bid_dollars: "0.4200"``, ``volume_fp:
"1234.00"``). Responses may carry either form, so every reader here accepts
both and always returns prices in cents (floats, since some markets trade in
sub-penny increments).
"""

from __future__ import annotations

from typing import Any

OPEN_STATUSES = {"open", "active"}


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_cents(raw: dict[str, Any], key: str) -> float | None:
    """Read a price in cents from either ``key`` (cents) or ``key_dollars`` (dollars)."""
    cents = _number(raw.get(key))
    if cents is not None:
        return cents
    dollars = _number(raw.get(key + "_dollars"))
    if dollars is not None:
        return round(dollars * 100, 2)
    return None


def quantity(raw: dict[str, Any], key: str) -> float:
    """Read a count/volume from either ``key`` or its fixed-point ``key_fp`` twin."""
    value = _number(raw.get(key))
    if value is None:
        value = _number(raw.get(key + "_fp"))
    return value or 0.0


def is_tradable(price: float | None) -> bool:
    """A resting ask/bid only exists strictly between 0 and 100 cents."""
    return price is not None and 0 < price < 100


def normalize_market(raw: dict[str, Any], event: dict[str, Any] | None = None,
                     category: str | None = None) -> dict[str, Any]:
    """Flatten a raw market (plus its parent event, if known) for scanning and display.

    ``category`` comes from the market's series; Kalshi dropped it from markets
    and deprecated it on events, which are only used as a fallback.
    """
    event = event or {}
    yes_bid = price_cents(raw, "yes_bid")
    yes_ask = price_cents(raw, "yes_ask")
    no_bid = price_cents(raw, "no_bid")
    no_ask = price_cents(raw, "no_ask")
    # Kalshi runs a single book: a NO bid is a YES ask seen from the other side.
    if no_bid is None and yes_ask is not None:
        no_bid = round(100 - yes_ask, 2)
    if no_ask is None and yes_bid is not None:
        no_ask = round(100 - yes_bid, 2)

    last = price_cents(raw, "last_price")
    if is_tradable(yes_bid) and is_tradable(yes_ask):
        chance = (yes_bid + yes_ask) / 2
    elif last:
        chance = last
    else:
        chance = None

    event_title = event.get("title") or ""
    outcome = raw.get("yes_sub_title") or raw.get("subtitle") or ""
    title = raw.get("title") or event_title or raw.get("ticker", "")
    if event_title and outcome and len(event.get("markets") or []) > 1:
        # "Who wins?: Bills" reads badly, so questions get a dash instead of a colon.
        title = f"{event_title} — {outcome}" if event_title.endswith(("?", "!", ".")) else f"{event_title}: {outcome}"

    status = (raw.get("status") or "").lower()
    return {
        "ticker": raw.get("ticker", ""),
        "event_ticker": raw.get("event_ticker") or event.get("event_ticker", ""),
        "series_ticker": event.get("series_ticker") or raw.get("series_ticker") or "",
        "title": title,
        "outcome": outcome,
        "category": category or event.get("category") or raw.get("category") or "Other",
        "status": "open" if status in OPEN_STATUSES else status,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "last_price": last,
        "chance": round(chance, 1) if chance is not None else None,
        "spread": round(yes_ask - yes_bid, 2) if is_tradable(yes_bid) and is_tradable(yes_ask) else None,
        "volume": quantity(raw, "volume"),
        "volume_24h": quantity(raw, "volume_24h"),
        "open_interest": quantity(raw, "open_interest"),
        "close_time": raw.get("close_time") or "",
        "rules": (raw.get("rules_primary") or "")[:500],
    }


def normalize_trade(raw: dict[str, Any]) -> dict[str, Any]:
    # taker_outcome_side (yes/no) replaced the deprecated taker_side; taker_book_side
    # says the same thing as bid (bought YES) / ask (bought NO).
    side = (raw.get("taker_outcome_side") or raw.get("taker_side") or "").lower()
    if not side:
        side = {"bid": "yes", "ask": "no"}.get((raw.get("taker_book_side") or "").lower(), "")
    return {
        "ticker": raw.get("ticker", ""),
        "count": quantity(raw, "count"),
        "yes_price": price_cents(raw, "yes_price"),
        "taker_side": side,
        "created_time": raw.get("created_time") or "",
    }


def flatten_events(events: list[dict[str, Any]], categories: dict[str, str] | None = None,
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split ``/events?with_nested_markets=true`` pages into (events, markets).

    ``categories`` maps series ticker to category (from ``/series``). The
    returned events keep only the fields the scanner needs plus the tickers
    of their open markets, so they stay small enough to cache.
    """
    categories = categories or {}
    out_events, out_markets = [], []
    for ev in events:
        category = categories.get(ev.get("series_ticker") or "")
        markets = [normalize_market(m, ev, category) for m in ev.get("markets") or []]
        open_markets = [m for m in markets if m["status"] == "open"]
        out_markets.extend(open_markets)
        out_events.append({
            "event_ticker": ev.get("event_ticker") or "",
            "series_ticker": ev.get("series_ticker") or "",
            "title": ev.get("title") or "",
            "category": category or ev.get("category") or "Other",
            "mutually_exclusive": bool(ev.get("mutually_exclusive")),
            "market_count": len(markets),
            "open_tickers": [m["ticker"] for m in open_markets],
        })
    return out_events, out_markets
