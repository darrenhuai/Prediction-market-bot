"""Made-up market data in Kalshi's API format, for trying the app without network access.

Prices drift a little on every refresh so the UI looks alive. One event is
deliberately mispriced so the arbitrage finder has something to show, and a
couple of markets get lopsided trade flow.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

# (event ticker, title, category, mutually exclusive, days to close, [(outcome, yes chance %)])
_EVENTS = [
    ("DEMO-FED-DEC", "Fed decision in December", "Economics", True, 70,
     [("Cut 50bps or more", 8), ("Cut 25bps", 57), ("Hold rates", 33), ("Hike", 2)]),
    ("DEMO-NYCTEMP", "Highest temperature in NYC tomorrow", "Climate", True, 1,
     [("Below 70°F", 15), ("70-71°F", 30), ("72-73°F", 35), ("74-75°F", 22), ("Above 75°F", 14)]),
    ("DEMO-BTC-FRI", "Bitcoin price on Friday at 5pm", "Crypto", False, 3,
     [("Above $110,000", 71), ("Above $115,000", 44), ("Above $120,000", 19), ("Above $125,000", 6)]),
    ("DEMO-OSCAR-PIC", "Best Picture winner", "Culture", True, 160,
     [("Film A", 31), ("Film B", 24), ("Film C", 17), ("Film D", 11), ("Film E", 7), ("Film F", 4)]),
    ("DEMO-NFL-KCBUF", "Chiefs vs Bills: who wins?", "Sports", True, 4,
     [("Chiefs", 45), ("Bills", 48)]),
    ("DEMO-SEARAIN", "Will it rain in Seattle tomorrow?", "Climate", False, 1, [("Yes", 62)]),
    ("DEMO-GDP-Q3", "US GDP growth above 2.0% in Q3?", "Economics", False, 35, [("Yes", 54)]),
    ("DEMO-SHUTDOWN", "Government shutdown before Oct 1?", "Politics", False, 7, [("Yes", 23)]),
    ("DEMO-STARSHIP", "Starship reaches orbit this month?", "Science", False, 6, [("Yes", 38)]),
    ("DEMO-CPI-SEP", "September CPI above 0.3%?", "Economics", False, 20, [("Yes", 41)]),
    ("DEMO-MAYOR", "City mayoral election winner", "Politics", True, 40,
     [("Candidate X", 58), ("Candidate Y", 34), ("Candidate Z", 6)]),
    ("DEMO-APPLE-AI", "Apple announces a new AI device this year?", "Tech", False, 98, [("Yes", 12)]),
    ("DEMO-GAS-4", "US average gas price above $3.50 on Oct 31?", "Economics", False, 37, [("Yes", 29)]),
    ("DEMO-TOPSONG", "Top song on the Billboard Hot 100 next week", "Culture", True, 6,
     [("Song One", 46), ("Song Two", 38), ("Song Three", 11)]),
]

# Markets whose recent trades are rigged to trigger the unusual-activity signal.
_HEAVY_YES = "DEMO-SHUTDOWN-YES"
_WHALE = "DEMO-STARSHIP-YES"


def _dollars(cents: float) -> str:
    return f"{cents / 100:.4f}"


class DemoSource:
    """Stands in for KalshiClient with the handful of calls the scanner makes."""

    def __init__(self, seed: int = 7):
        self._seed = seed

    def get_all_events(self, status: str = "open", max_pages: int = 50) -> list[dict[str, Any]]:
        # A new random draw every minute, so repeated refreshes show small moves.
        rng = random.Random(self._seed * 100_003 + int(time.time() // 60))
        now = datetime.now(timezone.utc)
        events = []
        for ticker, title, category, exclusive, days, outcomes in _EVENTS:
            markets = []
            for name, chance in outcomes:
                mid = min(97, max(3, chance + rng.choice([-1, 0, 0, 1])))
                spread = rng.choice([1, 1, 2, 3])
                yes_bid = max(1, mid - spread // 2 - (1 if spread == 1 else 0))
                yes_ask = min(99, yes_bid + spread)
                if ticker == "DEMO-NYCTEMP":  # overlapping bids: NO on every bracket is underpriced
                    yes_bid, yes_ask = chance, chance + 2
                mticker = f"{ticker}-{'YES' if name == 'Yes' else name.upper().replace(' ', '')[:10]}"
                volume = int(rng.uniform(2_000, 400_000) * (mid / 50 if mid < 50 else 1))
                if mticker in (_HEAVY_YES, _WHALE):
                    volume = 900_000  # keep them among the busiest markets the flow scan checks
                markets.append({
                    "ticker": mticker,
                    "event_ticker": ticker,
                    "title": title,
                    "yes_sub_title": name,
                    "status": "active",
                    "yes_bid_dollars": _dollars(yes_bid),
                    "yes_ask_dollars": _dollars(yes_ask),
                    "no_bid_dollars": _dollars(100 - yes_ask),
                    "no_ask_dollars": _dollars(100 - yes_bid),
                    "last_price_dollars": _dollars(mid),
                    "volume_fp": f"{volume}.00",
                    "volume_24h_fp": f"{int(volume * rng.uniform(0.03, 0.2))}.00",
                    "open_interest_fp": f"{int(volume * 0.4)}.00",
                    "close_time": (now + timedelta(days=days, hours=rng.randint(0, 12))).isoformat(),
                    "rules_primary": f"Demo market. Resolves YES if the outcome is: {name}.",
                })
            events.append({
                "event_ticker": ticker,
                "series_ticker": ticker.rsplit("-", 1)[0],
                "title": title,
                "category": category,
                "mutually_exclusive": exclusive,
                "markets": markets,
            })
        return events

    def get_trades(self, ticker: str | None = None, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        rng = random.Random(f"{self._seed}:{ticker}")
        yes_share = 0.9 if ticker == _HEAVY_YES else 0.5
        trades = []
        for i in range(40):
            side = "yes" if rng.random() < yes_share else "no"
            count = rng.randint(1, 30)
            if ticker == _WHALE and i == 3:
                count, side = 2_500, "yes"
            trades.append({"ticker": ticker, "taker_side": side, "count_fp": f"{count}.00",
                           "yes_price_dollars": "0.5000", "created_time": ""})
        return {"trades": trades[:limit]}

    def get_balance(self) -> dict[str, Any]:
        return {"balance": 100_000}  # $1,000.00 of pretend money
