"""Unit tests for src.common.kalshi_client.KalshiClient.

Uses httpx.MockTransport (built into httpx, no extra test dependency)
to fake the Kalshi API instead of hitting the network.
"""

from __future__ import annotations

import httpx
import pytest

from src.common.kalshi_client import KalshiClient


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch):
    """Isolate every test in this module from real Kalshi credentials.

    KalshiClient() reads KALSHI_* env vars at construction time, so a
    contributor with real credentials configured in their local .env would
    otherwise get different (and failing) results than CI, e.g. mock_client()
    picking the RSA auth path instead of the unauthenticated/email-password
    path a given test expects.
    """
    monkeypatch.delenv("KALSHI_EMAIL", raising=False)
    monkeypatch.delenv("KALSHI_PASSWORD", raising=False)
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)


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


class TestGetEvents:
    def test_requests_nested_markets_and_pages_through(self):
        pages = {None: {"events": [{"event_ticker": "A"}], "cursor": "c2"},
                 "c2": {"events": [{"event_ticker": "B"}], "cursor": ""}}
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            seen.append(params)
            return httpx.Response(200, json=pages[params.get("cursor")])

        events = mock_client(handler).get_all_events()
        assert [e["event_ticker"] for e in events] == ["A", "B"]
        assert seen[0]["with_nested_markets"] == "true"

    def test_stops_at_max_pages(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"events": [{"event_ticker": "X"}], "cursor": "more"})

        assert len(mock_client(handler).get_all_events(max_pages=3)) == 3


class TestRateLimitRetry:
    def test_retries_after_429(self, monkeypatch):
        monkeypatch.setattr("src.common.kalshi_client.time.sleep", lambda s: None)
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"markets": []})

        assert mock_client(handler).get_markets() == {"markets": []}
        assert len(calls) == 2


class TestRsaSignature:
    def test_signature_is_rsa_pss_over_timestamp_method_path(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        c = KalshiClient()
        c._private_key, c._api_key_id = key, "key-id"
        headers = c._rsa_auth_headers("GET", "/trade-api/v2/portfolio/balance")
        msg = (headers["KALSHI-ACCESS-TIMESTAMP"] + "GET/trade-api/v2/portfolio/balance").encode()
        import base64
        key.public_key().verify(  # raises InvalidSignature if the scheme is wrong
            base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]), msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )


class TestKeyTypes:
    def _write_key(self, tmp_path, key, password=None):
        from cryptography.hazmat.primitives import serialization

        enc = serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)
        path = tmp_path / "kalshi.pem"
        path.write_bytes(pem)
        return str(path)

    def test_ed25519_key_signs_requests(self, tmp_path, monkeypatch):
        import base64

        from cryptography.hazmat.primitives.asymmetric import ed25519

        key = ed25519.Ed25519PrivateKey.generate()
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", self._write_key(tmp_path, key))
        monkeypatch.setenv("KALSHI_API_KEY_ID", "key-id")
        c = KalshiClient()
        assert c.has_auth
        headers = c._rsa_auth_headers("GET", "/trade-api/v2/portfolio/balance")
        msg = (headers["KALSHI-ACCESS-TIMESTAMP"] + "GET/trade-api/v2/portfolio/balance").encode()
        key.public_key().verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]), msg)

    def test_password_protected_key_does_not_crash_startup(self, tmp_path, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", self._write_key(tmp_path, key, b"secret"))
        monkeypatch.setenv("KALSHI_API_KEY_ID", "key-id")
        assert not KalshiClient().has_auth

    def test_no_key_means_no_auth(self):
        assert not KalshiClient().has_auth


class TestEventsTruncation:
    def test_flags_when_more_pages_remain(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"events": [{"event_ticker": "X"}], "cursor": "more"})

        c = mock_client(handler)
        c.get_all_events(max_pages=2)
        assert c.events_truncated

    def test_not_flagged_when_all_pages_read(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"events": [{"event_ticker": "X"}], "cursor": ""})

        c = mock_client(handler)
        c.get_all_events(max_pages=2)
        assert not c.events_truncated
