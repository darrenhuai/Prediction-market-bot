"""Unit tests for src.common.kalshi_client.KalshiClient.

Uses httpx.MockTransport (built into httpx, no extra test dependency)
to fake the Kalshi API instead of hitting the network.
"""

from __future__ import annotations

import httpx
import pytest

from src.common.kalshi_client import KalshiClient


@pytest.fixture
def client(monkeypatch):
    """A KalshiClient with no credentials configured, network disabled."""
    monkeypatch.delenv("KALSHI_EMAIL", raising=False)
    monkeypatch.delenv("KALSHI_PASSWORD", raising=False)
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    return KalshiClient()


def mock_client(handler) -> KalshiClient:
    """Build a KalshiClient whose httpx session is backed by a MockTransport."""
    c = KalshiClient()
    c._session = httpx.Client(base_url=c.base, transport=httpx.MockTransport(handler))
    return c


class TestGetMarkets:
    def test_passes_status_and_limit(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"markets": []})

        c = mock_client(handler)
        c.get_markets(status="closed", limit=50)
        assert captured["params"]["status"] == "closed"
        assert captured["params"]["limit"] == "50"

    def test_omits_cursor_and_series_ticker_when_not_given(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"markets": []})

        c = mock_client(handler)
        c.get_markets()
        assert "cursor" not in captured["params"]
        assert "series_ticker" not in captured["params"]

    def test_includes_cursor_when_given(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"markets": []})

        c = mock_client(handler)
        c.get_markets(cursor="abc123")
        assert captured["params"]["cursor"] == "abc123"

    def test_raises_on_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        c = mock_client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            c.get_markets()


class TestGetAllMarkets:
    def test_pages_through_cursor_until_exhausted(self):
        pages = [
            {"markets": [{"ticker": "A"}, {"ticker": "B"}], "cursor": "page2"},
            {"markets": [{"ticker": "C"}], "cursor": None},
        ]
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            page = pages[calls["n"]]
            calls["n"] += 1
            return httpx.Response(200, json=page)

        c = mock_client(handler)
        results = c.get_all_markets()
        assert [m["ticker"] for m in results] == ["A", "B", "C"]
        assert calls["n"] == 2

    def test_stops_on_empty_markets_even_with_cursor(self):
        """Defensive: an empty page should stop pagination even if a
        (buggy) cursor is still returned, to avoid an infinite loop."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"markets": [], "cursor": "keeps-going"})

        c = mock_client(handler)
        results = c.get_all_markets()
        assert results == []

    def test_returns_empty_list_when_no_markets_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        c = mock_client(handler)
        assert c.get_all_markets() == []


class TestAuthSelection:
    def test_unauthenticated_endpoint_sends_no_auth_header(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={})

        c = mock_client(handler)
        c.get_exchange_status()
        assert "authorization" not in captured["headers"]
        assert "kalshi-access-key" not in captured["headers"]

    def test_auth_endpoint_without_credentials_raises(self, monkeypatch):
        monkeypatch.delenv("KALSHI_EMAIL", raising=False)
        monkeypatch.delenv("KALSHI_PASSWORD", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            # /login itself fails since there's no email/password configured.
            return httpx.Response(401, json={"error": "invalid credentials"})

        c = mock_client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            c.get_balance()

    def test_auth_endpoint_sends_bearer_token_after_login(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path.endswith("/login"):
                return httpx.Response(200, json={"token": "tok_abc"})
            return httpx.Response(200, json={"balance": 100})

        c = mock_client(handler)
        c._email, c._password = "a@b.com", "pw"
        c.get_balance()

        assert calls[0].url.path.endswith("/login")
        assert calls[1].headers["authorization"] == "Bearer tok_abc"

    def test_reuses_cached_token_without_relogging_in(self):
        login_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/login"):
                login_calls["n"] += 1
                return httpx.Response(200, json={"token": "tok_abc"})
            return httpx.Response(200, json={"balance": 100})

        c = mock_client(handler)
        c._email, c._password = "a@b.com", "pw"
        c.get_balance()
        c.get_balance()
        assert login_calls["n"] == 1


class TestCreateOrder:
    def test_includes_yes_price_only_when_given(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/login"):
                return httpx.Response(200, json={"token": "tok"})
            import json as _json

            captured["json"] = _json.loads(request.content)
            return httpx.Response(200, json={"order": {}})

        c = mock_client(handler)
        c._email, c._password = "a@b.com", "pw"
        c.create_order("TICKER-X", "yes", "buy", "limit", 10, yes_price=55)

        assert captured["json"]["yes_price"] == 55
        assert "no_price" not in captured["json"]
        assert "client_order_id" in captured["json"]
