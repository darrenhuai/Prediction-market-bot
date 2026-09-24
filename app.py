"""Web app for the Kalshi scanner.

    uv run app.py              # live Kalshi data at http://localhost:8000
    uv run app.py --demo       # made-up data, no network or account needed
    uv run app.py --host 0.0.0.0 --port 8000   # let others on your network open it

Uses only the Python standard library for the server; the page itself lives in web/.
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bot import make_scanner, setup_logging
from src.scanner.service import Scanner

log = logging.getLogger("kalshi-bot")
WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 64 * 1024


def refresh_and_alert(scanner: Scanner) -> None:
    try:
        if scanner.refresh() and not scanner.snapshot.get("error"):
            scanner.alerter.send(scanner.all_opportunities())
    except Exception:
        log.exception("Refresh failed")


def auto_refresh(scanner: Scanner, stop: threading.Event) -> None:
    while not stop.is_set():
        refresh_and_alert(scanner)
        stop.wait(scanner.settings["refresh_minutes"] * 60)


def make_handler(scanner: Scanner):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the console for alerts, not every request
            log.debug("%s - %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("Request too large")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return data

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                return self._json(scanner.state())
            if path == "/api/status":
                return self._json({"updated_at": scanner.snapshot.get("updated_at"),
                                   "refreshing": scanner.is_refreshing, "error": scanner.snapshot.get("error")})
            name = "index.html" if path == "/" else path.lstrip("/")
            file = (WEB_DIR / name).resolve()
            if WEB_DIR.resolve() not in file.parents or not file.is_file():
                return self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(HTTPStatus.OK, file.read_bytes(), ctype)

        def do_POST(self):
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
                return self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            except (KeyError, ValueError, TypeError) as e:
                return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

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
    stop = threading.Event()
    threading.Thread(target=auto_refresh, args=(scanner, stop), daemon=True).start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(scanner))
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
