"""Log and (optionally) email new opportunities, without repeating the same alert every scan."""

from __future__ import annotations

import json
import logging
import os
import smtplib
import time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

log = logging.getLogger("kalshi-bot")

REALERT_AFTER_SECONDS = 6 * 3600  # repeat an unchanged alert at most every 6 hours
REALERT_IMPROVEMENT_CENTS = 1.0   # ...or sooner if the edge grows by at least this much


def describe(opp: dict[str, Any]) -> tuple[str, str]:
    """Plain-English (title, body) for an opportunity."""
    if opp["kind"] == "pick":
        return (
            f"+EV pick: buy {opp['side']} on {opp['ticker']}",
            f"{opp['title']}\nBuy {opp['side']} at {opp['price']:g}c. You estimate YES at {opp['your_chance']}%, "
            f"the market says {opp['market_chance']}%. Expected profit: +{opp['ev_cents']:.1f}c per contract after fees.",
        )
    if opp["kind"] == "arbitrage":
        legs = ", ".join(f"{leg['outcome']} @ {leg['price']:g}c" for leg in opp["legs"])
        note = "Locked in." if opp["guaranteed"] else "Only locked in if one of these outcomes must happen."
        return (
            f"Arbitrage: {opp['event_ticker']}",
            f"{opp['title']}\nBuy {opp['side']} on every outcome ({legs}). Cost {opp['cost_cents']:.1f}c incl. fees, "
            f"pays at least {opp['payout_cents']}c: +{opp['profit_cents']:.1f}c per bundle. {note}",
        )
    return (f"Unusual activity: {opp['ticker']}", f"{opp.get('title', opp['ticker'])}\n{opp['reason']}")


def _score(opp: dict[str, Any]) -> float:
    return opp.get("ev_cents", opp.get("profit_cents", 0.0))


class Alerter:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        try:
            self.seen: dict[str, dict[str, float]] = json.loads(state_path.read_text())
        except (OSError, ValueError):
            self.seen = {}

    def new_alerts(self, opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return opportunities worth alerting on now and remember them."""
        fresh, now = [], time.time()
        for opp in opportunities:
            prev = self.seen.get(opp["key"])
            if prev and now - prev["at"] < REALERT_AFTER_SECONDS and _score(opp) < prev["score"] + REALERT_IMPROVEMENT_CENTS:
                continue
            fresh.append(opp)
            self.seen[opp["key"]] = {"at": now, "score": _score(opp)}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.seen, indent=2))
        return fresh

    def send(self, opportunities: list[dict[str, Any]]) -> None:
        for opp in self.new_alerts(opportunities):
            title, body = describe(opp)
            log.info("ALERT: %s | %s", title, body.replace("\n", " | "))
            send_email("[Kalshi Bot] " + title, body)


def send_email(subject: str, body: str) -> None:
    to, sender, password = (os.getenv(k, "") for k in ("ALERT_EMAIL_TO", "ALERT_EMAIL_FROM", "ALERT_EMAIL_PASSWORD"))
    if not (to and sender and password):
        return
    try:
        msg = MIMEText(body)
        msg["Subject"], msg["From"], msg["To"] = subject, sender, to
        host, port = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com"), int(os.getenv("ALERT_SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, [to], msg.as_string())
        log.info("Email sent to %s", to)
    except Exception as e:  # never let email trouble stop a scan
        log.warning("Email failed: %s", e)
