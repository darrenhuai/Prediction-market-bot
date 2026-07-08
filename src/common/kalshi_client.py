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

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://trading-api.kalshi.com/trade-api/v2")

class KalshiClient:
    """Thin wrapper around the Kalshi trade API.

    Supports two auth modes:
      - RSA key-pair auth (KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH), used
        when both are configured and the key loads successfully.
      - Email/password auth (KALSHI_EMAIL + KALSHI_PASSWORD), used as a
        fallback for endpoints that require auth.

    All four env vars are optional at construction time; unauthenticated
    endpoints (e.g. get_markets) work without any credentials.
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

    def _load_key(self) -> None:
        try:
            from cryptography.hazmat.primitives import serialization
            with open(self._private_key_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        except OSError as e:
            logger.warning("Could not read private key file %s: %s", self._private_key_path, e)
        except ValueError as e:
            # Raised by cryptography for malformed/unsupported key data.
            logger.warning("Could not parse private key %s: %s", self._private_key_path, e)

        if self._private_key_path and self._private_key is None:
            logger.warning(
                "KALSHI_PRIVATE_KEY_PATH is set but no key was loaded; "
                "falling back to email/password login if credentials are available."
            )
        if self._private_key and not self._api_key_id:
            logger.warning(
                "Private key loaded but KALSHI_API_KEY_ID is not set; "
                "RSA auth headers cannot be built without it."
            )

    def _rsa_auth_headers(self, method: str, path: str) -> dict[str, str]:
        import datetime

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        ts = str(int(datetime.datetime.now().timestamp() * 1000))
        msg_parts = ts + method.upper() + path
        msg = msg_parts.encode("utf-8")
        sig = self._private_key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
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
