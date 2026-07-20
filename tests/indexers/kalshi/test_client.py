"""Unit tests for src.indexers.kalshi.client.KalshiClient.

Uses httpx.MockTransport (built into httpx, no extra test dependency) to
fake the Kalshi API instead of hitting the network. This is the indexer's
backfill client (pagination over markets/trades), distinct from
src.common.kalshi_client.KalshiClient which is the trading client -- see
tests/common/test_kalshi_client.py for that one.
"""

from __future__ import annotations

import httpx
import pytest

from src.indexers.kalshi.client import KalshiClient


def mock_client(handler) -> KalshiClient:
    """Build a KalshiClient whose httpx session is backed by a MockTransport."""
    c = KalshiClient()
    c.client = httpx.Client(base_url=c.host, transport=httpx.MockTransport(handler))
    return c


def _market(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "event_ticker": "EVT",
        "status": "open",
    }


def _trade(trade_id: str) -> dict:
    return {
        "trade_id": trade_id,
        "ticker": "TICK",
        "count": 1,
        "yes_price": 50,
        "no_price": 50,
        "taker_side": "yes",
        "created_time": "2024-01-01T00:00:00Z",
    }


class TestGetMarketTrades:
    def test_pages_through_cursor_until_exhausted(self):
        pages = [
            {"trades": [_trade("t1"), _trade("t2")], "cursor": "page2"},
            {"trades": [_trade("t3")], "cursor": None},
        ]
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            page = pages[calls["n"]]
            calls["n"] += 1
            return httpx.Response(200, json=page)

        c = mock_client(handler)
        trades = c.get_market_trades("TICK", verbose=False)
        assert [t.trade_id for t in trades] == ["t1", "t2", "t3"]
        assert calls["n"] == 2

    def test_passes_min_ts_and_max_ts(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"trades": []})

        c = mock_client(handler)
        c.get_market_trades("TICK", verbose=False, min_ts=100, max_ts=200)
        assert captured["params"]["min_ts"] == "100"
        assert captured["params"]["max_ts"] == "200"

    def test_omits_min_ts_and_max_ts_when_not_given(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"trades": []})

        c = mock_client(handler)
        c.get_market_trades("TICK", verbose=False)
        assert "min_ts" not in captured["params"]
        assert "max_ts" not in captured["params"]

    def test_stops_when_no_cursor_even_with_trades(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"trades": [_trade("t1")], "cursor": None})

        c = mock_client(handler)
        trades = c.get_market_trades("TICK", verbose=False)
        assert [t.trade_id for t in trades] == ["t1"]


class TestListAllMarkets:
    def test_pages_through_cursor_until_exhausted(self):
        pages = [
            {"markets": [_market("A"), _market("B")], "cursor": "page2"},
            {"markets": [_market("C")], "cursor": None},
        ]
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            page = pages[calls["n"]]
            calls["n"] += 1
            return httpx.Response(200, json=page)

        c = mock_client(handler)
        markets = c.list_all_markets()
        assert [m.ticker for m in markets] == ["A", "B", "C"]
        assert calls["n"] == 2

    def test_returns_empty_list_when_no_markets_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        c = mock_client(handler)
        assert c.list_all_markets() == []


class TestIterMarkets:
    def test_yields_each_page_and_stops_on_missing_cursor(self):
        pages = [
            {"markets": [_market("A")], "cursor": "page2"},
            {"markets": [_market("B")], "cursor": None},
        ]
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            page = pages[calls["n"]]
            calls["n"] += 1
            return httpx.Response(200, json=page)

        c = mock_client(handler)
        results = list(c.iter_markets())
        assert [m.ticker for page, _ in results for m in page] == ["A", "B"]
        assert results[0][1] == "page2"
        assert results[1][1] is None

    def test_passes_min_close_ts_and_max_close_ts(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"markets": []})

        c = mock_client(handler)
        list(c.iter_markets(min_close_ts=10, max_close_ts=20))
        assert captured["params"]["min_close_ts"] == "10"
        assert captured["params"]["max_close_ts"] == "20"


class TestGetRecentTrades:
    def test_returns_parsed_trades(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"trades": [_trade("t1")]})

        c = mock_client(handler)
        trades = c.get_recent_trades(limit=5)
        assert [t.trade_id for t in trades] == ["t1"]

    def test_raises_on_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        c = mock_client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            c.get_recent_trades()
