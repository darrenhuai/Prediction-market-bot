from __future__ import annotations
import os, time, base64, hashlib
import httpx
from dotenv import load_dotenv
load_dotenv()

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://trading-api.kalshi.com/trade-api/v2")

class KalshiClient:
    def __init__(self):
        self.base = BASE_URL
        self._token = None
        self._token_expiry = 0.0
        self._email = os.getenv("KALSHI_EMAIL")
        self._password = os.getenv("KALSHI_PASSWORD")
        self._api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self._private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        self._private_key = None
        self._session = httpx.Client(base_url=self.base, timeout=15)
        if self._private_key_path:
            self._load_key()

    def _load_key(self):
        try:
            from cryptography.hazmat.primitives import serialization
            with open(self._private_key_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        except Exception as e:
            print(f"Warning: could not load private key: {e}")

    def _rsa_auth_headers(self, method, path):
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

    def _login(self):
        resp = self._session.post("/login", json={"email": self._email, "password": self._password})
        resp.raise_for_status()
        self._token = resp.json().get("token")
        self._token_expiry = time.time() + 25 * 60

    def _get(self, path, params=None, auth=False):
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

    def _post(self, path, body):
        if self._private_key and self._api_key_id:
            headers = self._rsa_auth_headers("POST", "/trade-api/v2" + path)
        else:
            if not self._token or time.time() > self._token_expiry:
                self._login()
            headers = {"Authorization": f"Bearer {self._token}"}
        resp = self._session.post(path, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def get_exchange_status(self):
        return self._get("/exchange/status")

    def get_markets(self, status="open", limit=100, cursor=None, series_ticker=None):
        params = {"status": status, "limit": limit}
        if cursor: params["cursor"] = cursor
        if series_ticker: params["series_ticker"] = series_ticker
        return self._get("/markets", params=params)

    def get_all_markets(self, status="open", series_ticker=None):
        results, cursor = [], None
        while True:
            resp = self.get_markets(status=status, cursor=cursor, limit=1000, series_ticker=series_ticker)
            markets = resp.get("markets") or []
            results.extend(markets)
            cursor = resp.get("cursor")
            if not cursor or not markets: break
        return results

    def get_market(self, ticker):
        return self._get(f"/markets/{ticker}")

    def get_orderbook(self, ticker, depth=10):
        return self._get(f"/markets/{ticker}/orderbook", params={"depth": depth})

    def get_trades(self, ticker=None, limit=100, cursor=None):
        params = {"limit": limit}
        if ticker: params["ticker"] = ticker
        if cursor: params["cursor"] = cursor
        return self._get("/markets/trades", params=params)

    def get_balance(self):
        return self._get("/portfolio/balance", auth=True)

    def get_positions(self, limit=100, cursor=None):
        params = {"limit": limit}
        if cursor: params["cursor"] = cursor
        return self._get("/portfolio/positions", params=params, auth=True)

    def get_all_positions(self):
        results, cursor = [], None
        while True:
            resp = self.get_positions(cursor=cursor)
            positions = resp.get("market_positions") or []
            results.extend(positions)
            cursor = resp.get("cursor")
            if not cursor or not positions: break
        return results

    def get_fills(self, ticker=None, limit=100):
        params = {"limit": limit}
        if ticker: params["ticker"] = ticker
        return self._get("/portfolio/fills", params=params, auth=True)

    def create_order(self, ticker, side, action, order_type, count, yes_price=None, no_price=None):
        import uuid
        body = {"ticker": ticker, "side": side, "action": action, "type": order_type, "count": count, "client_order_id": str(uuid.uuid4())}
        if yes_price is not None: body["yes_price"] = yes_price
        if no_price is not None: body["no_price"] = no_price
        return self._post("/portfolio/orders", body)
