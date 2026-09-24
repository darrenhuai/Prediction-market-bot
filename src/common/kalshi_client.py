from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# trading-api.kalshi.com is the retired host; all markets are served from here now.
BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
RATE_LIMIT_RETRIES = 3

class KalshiClient:
    """Thin wrapper around the Kalshi trade API.

    Auth modes:
      - API-key auth (KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH), used when
        both are configured and the key loads. Kalshi issues RSA and Ed25519
        keys; both are supported.
      - Email/password (KALSHI_EMAIL + KALSHI_PASSWORD) is legacy: Kalshi's
        current API has no /login endpoint, so this path only fails. It is
        kept so old configs get an error instead of a crash.

    All env vars are optional; public endpoints (markets, events, trades)
    work without any credentials.
    """

    def __init__(self) -> None:
        self.base = BASE_URL
        self._token: str | None = None
        self._token_expiry = 0.0
        self._email = os.getenv("KALSHI_EMAIL")
        self._password = os.getenv("KALSHI_PASSWORD")
        self._api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self._private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        self._private_key: Any = None
        self._session = httpx.Client(base_url=self.base, timeout=15)
        if self._private_key_path:
            self._load_key()

    @property
    def has_auth(self) -> bool:
        """True when API-key auth is configured, i.e. account endpoints like balance can work."""
        return bool(self._private_key and self._api_key_id)

    def _load_key(self) -> None:
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
            with open(self._private_key_path, "rb") as f:
                key = serialization.load_pem_private_key(f.read(), password=None)
            if isinstance(key, (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)):
                self._private_key = key
            else:
                logger.warning("Unsupported key type %s in %s; Kalshi keys are RSA or Ed25519.",
                               type(key).__name__, self._private_key_path)
        except OSError as e:
            logger.warning("Could not read private key file %s: %s", self._private_key_path, e)
        except (ValueError, TypeError) as e:
            # ValueError: malformed key data. TypeError: the key file is password-protected.
            logger.warning("Could not load private key %s: %s", self._private_key_path, e)

        if self._private_key_path and self._private_key is None:
            logger.warning(
                "KALSHI_PRIVATE_KEY_PATH is set but no key was loaded, so account "
                "features (like your balance) are off. Public market data still works."
            )
        if self._private_key and not self._api_key_id:
            logger.warning(
                "Private key loaded but KALSHI_API_KEY_ID is not set; "
                "auth headers cannot be built without it."
            )

    def _rsa_auth_headers(self, method: str, path: str) -> dict[str, str]:
        """Signed auth headers. (Named for RSA, but Ed25519 keys are signed here too.)"""
        import datetime

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ed25519, padding
        ts = str(int(datetime.datetime.now().timestamp() * 1000))
        msg_parts = ts + method.upper() + path
        msg = msg_parts.encode("utf-8")
        if isinstance(self._private_key, ed25519.Ed25519PrivateKey):
            sig = self._private_key.sign(msg)
        else:
            # Kalshi verifies RSA-PSS (SHA-256, digest-length salt) signatures.
            sig = self._private_key.sign(
                msg,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
        sig_b64 = base64.b64encode(sig).decode("utf-8")
        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "Content-Type": "application/json",
        }

    def _login(self) -> None:
        resp = self._session.post("/login", json={"email": self._email, "password": self._password})
        resp.raise_for_status()
        self._token = resp.json().get("token")
        self._token_expiry = time.time() + 25 * 60

    def _get(self, path: str, params: dict[str, Any] | None = None, auth: bool = False) -> dict[str, Any]:
        if self._private_key and self._api_key_id:
            headers = self._rsa_auth_headers("GET", "/trade-api/v2" + path)
        elif auth:
            if not self._token or time.time() > self._token_expiry:
                self._login()
            headers = {"Authorization": f"Bearer {self._token}"}
        else:
            headers = {}
        resp = self._session.get(path, params=params, headers=headers)
        # Back off briefly on rate limiting instead of failing the whole scan.
        for attempt in range(RATE_LIMIT_RETRIES):
            if resp.status_code != 429:
                break
            time.sleep(float(resp.headers.get("Retry-After") or 2 ** attempt))
            resp = self._session.get(path, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._private_key and self._api_key_id:
            headers = self._rsa_auth_headers("POST", "/trade-api/v2" + path)
        else:
            if not self._token or time.time() > self._token_expiry:
                self._login()
            headers = {"Authorization": f"Bearer {self._token}"}
        resp = self._session.post(path, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def get_exchange_status(self) -> dict[str, Any]:
        """Return the current Kalshi exchange status (open/closed)."""
        return self._get("/exchange/status")

    def get_markets(
        self,
        status: str = "open",
        limit: int = 100,
        cursor: str | None = None,
        series_ticker: str | None = None,
    ) -> dict[str, Any]:
        params = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._get("/markets", params=params)

    def get_all_markets(self, status: str = "open", series_ticker: str | None = None) -> list[dict[str, Any]]:
        """Page through get_markets() and return every market as a flat list."""
        results, cursor = [], None
        while True:
            resp = self.get_markets(status=status, cursor=cursor, limit=1000, series_ticker=series_ticker)
            markets = resp.get("markets") or []
            results.extend(markets)
            cursor = resp.get("cursor")
            if not cursor or not markets:
                break
        return results

    def get_events(
        self,
        status: str = "open",
        limit: int = 200,
        cursor: str | None = None,
        with_nested_markets: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"status": status, "limit": limit}
        if with_nested_markets:
            params["with_nested_markets"] = "true"
        if cursor:
            params["cursor"] = cursor
        return self._get("/events", params=params)

    def get_all_events(self, status: str = "open", max_pages: int = 50) -> list[dict[str, Any]]:
        """Page through get_events() (with nested markets), stopping after ``max_pages``.

        Sets ``self.events_truncated`` when it stopped early with more pages left.
        """
        results, cursor = [], None
        self.events_truncated = False
        for page in range(max_pages):
            resp = self.get_events(status=status, cursor=cursor)
            events = resp.get("events") or []
            results.extend(events)
            cursor = resp.get("cursor")
            if not cursor or not events:
                break
            if page == max_pages - 1:
                self.events_truncated = True
                logger.warning("Stopped after %d pages of events; more are available.", max_pages)
        return results

    def get_series_list(self) -> list[dict[str, Any]]:
        """Every series (one call); each has the ``category`` that events no longer carry."""
        return self._get("/series").get("series") or []

    def get_market(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}")

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}/orderbook", params={"depth": depth})

    def get_trades(self, ticker: str | None = None, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets/trades", params=params)

    def get_balance(self) -> dict[str, Any]:
        return self._get("/portfolio/balance", auth=True)

    def get_positions(self, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._get("/portfolio/positions", params=params, auth=True)

    def get_all_positions(self) -> list[dict[str, Any]]:
        """Page through get_positions() and return every position as a flat list."""
        results, cursor = [], None
        while True:
            resp = self.get_positions(cursor=cursor)
            positions = resp.get("market_positions") or []
            results.extend(positions)
            cursor = resp.get("cursor")
            if not cursor or not positions:
                break
        return results

    def get_fills(self, ticker: str | None = None, limit: int = 100) -> dict[str, Any]:
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        return self._get("/portfolio/fills", params=params, auth=True)

    def create_order(
        self,
        ticker: str,
        side: str,
        action: str,
        order_type: str,
        count: int,
        yes_price: int | None = None,
        no_price: int | None = None,
    ) -> dict[str, Any]:
        """Submit an order. Exactly one of yes_price/no_price should be set for limit orders."""
        import uuid
        body: dict[str, Any] = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "type": order_type,
            "count": count,
            "client_order_id": str(uuid.uuid4()),
        }
        if yes_price is not None:
            body["yes_price"] = yes_price
        if no_price is not None:
            body["no_price"] = no_price
        return self._post("/portfolio/orders", body)
