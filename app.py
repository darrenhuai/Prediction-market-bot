"""Web app for the Kalshi scanner.

    uv run app.py              # live Kalshi data at http://localhost:8000
    uv run app.py --demo       # made-up data, no network or account needed
    uv run app.py --host 0.0.0.0 --port 8000   # let others on your network open it

Uses only the Python standard library for the server; the page itself lives in web/.
"""

from __future__ import annotations

import argparse
import gzip
import ipaddress
import json
import logging
import mimetypes
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bot import make_scanner, setup_logging
from src.scanner.service import SETTING_BOUNDS, Scanner

log = logging.getLogger("kalshi-bot")
WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 64 * 1024
REQUEST_TIMEOUT_SECONDS = 30
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
}


def refresh_and_alert(scanner: Scanner) -> None:
    try:
        if scanner.refresh() and not scanner.snapshot.get("error"):
            scanner.alerter.send(scanner.all_opportunities())
    except Exception:
        log.exception("Refresh failed")


def auto_refresh(scanner: Scanner, stop: threading.Event) -> None:
    max_wait = SETTING_BOUNDS["refresh_minutes"][1] * 60
    while not stop.is_set():
        refresh_and_alert(scanner)
        stop.wait(min(scanner.settings["refresh_minutes"] * 60, max_wait))


def _reject_constant(name: str):
    raise ValueError(f"{name} is not a number")


def host_allowed(host_header: str, extra_hosts: set[str]) -> bool:
    """Only answer to localhost, raw IP addresses, or the name passed to --host.

    Blocks DNS rebinding: a malicious site's own domain pointed at 127.0.0.1
    arrives with that domain in the Host header.
    """
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6 literal, e.g. [::1]:8000
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    if host in ("localhost", *extra_hosts):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def make_handler(scanner: Scanner, extra_hosts: frozenset[str] = frozenset()):
    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT_SECONDS  # drop clients that stall mid-request

        def log_message(self, fmt, *args):  # keep the console for alerts, not every request
            log.debug("%s - %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            if len(body) > 1024 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
                body = gzip.compress(body, compresslevel=5)
                encoded = True
            else:
                encoded = False
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if encoded:
                self.send_header("Content-Encoding", "gzip")
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(payload, allow_nan=False).encode(), "application/json")

        def _error(self, status: int, message: str) -> None:
            self._json({"error": message}, status)

        def _host_ok(self) -> bool:
            if host_allowed(self.headers.get("Host") or "", extra_hosts):
                return True
            self._error(HTTPStatus.FORBIDDEN, "Unknown host")
            return False

        def _same_origin(self) -> bool:
            """Refuse writes started by another website (CSRF)."""
            if (self.headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none"):
                return False
            origin = self.headers.get("Origin")
            return origin is None or urlsplit(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

        def _body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError as e:
                raise ValueError("Bad Content-Length") from e
            if not 0 <= length <= MAX_BODY:
                raise ValueError("Request too large")
            data = json.loads(self.rfile.read(length) or b"{}", parse_constant=_reject_constant)
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return data

        def do_GET(self):
            if not self._host_ok():
                return
            url = urlsplit(self.path)
            try:
                if url.path == "/api/state":
                    return self._json(scanner.state())
                if url.path == "/api/status":
                    return self._json({"updated_at": scanner.snapshot.get("updated_at"),
                                       "refreshing": scanner.is_refreshing, "error": scanner.snapshot.get("error")})
                if url.path == "/api/markets":
                    return self._json({"updated_at": scanner.snapshot.get("updated_at"), "markets": scanner.markets()})
                if url.path == "/api/market":
                    market = scanner.market((parse_qs(url.query).get("ticker") or [""])[0])
                    return self._json(market) if market else self._error(HTTPStatus.NOT_FOUND, "Unknown market")
                return self._static(url.path)
            except Exception:
                log.exception("GET %s failed", url.path)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Something went wrong")

        def _static(self, path: str) -> None:
            name = "index.html" if path == "/" else path.lstrip("/")
            try:
                root = WEB_DIR.resolve()
                file = (root / name).resolve()
                ok = root in file.parents and file.is_file()
            except (ValueError, OSError):  # e.g. NUL bytes or over-long names in the path
                ok = False
            if not ok:
                return self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(HTTPStatus.OK, file.read_bytes(), ctype)

        def do_POST(self):
            if not self._host_ok():
                return
            if not self._same_origin():
                return self._error(HTTPStatus.FORBIDDEN, "Requests from other websites are not allowed")
            if self.headers.get_content_type() != "application/json":
                return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/json")
            try:
                body = self._body()
                if self.path == "/api/refresh":
                    threading.Thread(target=refresh_and_alert, args=(scanner,), daemon=True).start()
                    time.sleep(0.05)  # let the refresh flag flip before the UI polls
                    return self._json({"ok": True})
                if self.path == "/api/estimate":
                    chance = body.get("chance")
                    scanner.set_estimate(str(body["ticker"]), None if chance in (None, "") else float(chance))
                    return self._json({"ok": True})
                if self.path == "/api/settings":
                    scanner.update_settings(body)
                    return self._json({"ok": True})
                return self._error(HTTPStatus.NOT_FOUND, "Not found")
            except (KeyError, ValueError, TypeError, OverflowError, RecursionError) as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
            except Exception:
                log.exception("POST %s failed", self.path)
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Something went wrong")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="use made-up demo data")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other devices on your network")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="open the page in your browser")
    args = parser.parse_args()

    setup_logging()
    scanner = make_scanner(args.demo)
    extra_hosts = frozenset({args.host.lower()} - {"0.0.0.0", "::"})
    try:
        server = ThreadingHTTPServer((args.host, args.port), make_handler(scanner, extra_hosts))
    except OSError as e:
        log.error("Can't start on port %d (%s). Is the app already running? "
                  "Try another port: uv run app.py --port %d", args.port, e.strerror or e, args.port + 1)
        sys.exit(1)
    server.daemon_threads = True

    stop = threading.Event()
    threading.Thread(target=auto_refresh, args=(scanner, stop), daemon=True).start()
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    log.info("Prediction Market Bot (%s data) running at %s  -  Ctrl+C to stop", scanner.mode, url)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
