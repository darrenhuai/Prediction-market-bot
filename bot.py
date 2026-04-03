import argparse, json, logging, os, smtplib, sys, time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

DEFAULT_INTERVAL = int(os.getenv("BOT_INTERVAL_SECONDS", "300"))
MIN_EV = float(os.getenv("MIN_EV_THRESHOLD", "0.02"))
MIN_VOLUME = int(os.getenv("MIN_VOLUME", "50"))
LARGE_TRADE = int(os.getenv("LARGE_TRADE_THRESHOLD", "50"))
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_PASS = os.getenv("ALERT_EMAIL_PASSWORD", "")
ALERT_SMTP_HOST = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT = int(os.getenv("ALERT_SMTP_PORT", "587"))
WATCH_SERIES = [s.strip() for s in os.getenv("WATCH_SERIES", "").split(",") if s.strip()]
MARKET_FETCH_LIMIT = 200  # fetch this many markets per run to avoid rate limits

OUTPUT_DIR = Path("output")
LOG_FILE = OUTPUT_DIR / "alerts.log"
STATE_FILE = OUTPUT_DIR / "bot_state.json"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE)]
)
log = logging.getLogger("kalshi-bot")

def now_str():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_ev": {}, "seen_flow": {}, "runs": 0, "started": now_str()}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

def send_email(subject, body):
    if not (ALERT_EMAIL_TO and ALERT_EMAIL_FROM and ALERT_EMAIL_PASS):
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = ALERT_EMAIL_FROM
        msg["To"] = ALERT_EMAIL_TO
        with smtplib.SMTP(ALERT_SMTP_HOST, ALERT_SMTP_PORT) as s:
            s.starttls()
            s.login(ALERT_EMAIL_FROM, ALERT_EMAIL_PASS)
            s.sendmail(ALERT_EMAIL_FROM, [ALERT_EMAIL_TO], msg.as_string())
        log.info("Email sent to " + ALERT_EMAIL_TO)
    except Exception as e:
        log.warning("Email failed: " + str(e))

def alert(title, body):
    log.info("ALERT: " + title + " | " + body)
    send_email("[Kalshi Bot] " + title, body)

def refresh_markets(client):
    from src.common.db import get_conn, upsert_markets
    conn = get_conn()
    # Fetch a limited batch to avoid rate limits - rotates through markets over time
    resp = client.get_markets(status="open", limit=MARKET_FETCH_LIMIT)
    markets = resp.get("markets") or []
    if WATCH_SERIES:
        markets = [m for m in markets if any(s.upper() in (m.get("series_ticker") or "").upper() for s in WATCH_SERIES)]
    n = upsert_markets(conn, markets)
    conn.close()
    return n

def scan_ev(state):
    from src.common.db import get_conn
    from src.common.util import ev_yes, ev_no, remove_vig, kelly_fraction
    conn = get_conn()
    rows = conn.execute(
        "SELECT ticker,title,yes_bid,yes_ask,no_bid,no_ask,volume,open_interest,close_time,event_ticker FROM markets WHERE status='open' AND yes_bid>0 AND no_bid>0 AND volume>=? ORDER BY volume DESC",
        [MIN_VOLUME]
    ).fetchall()
    conn.close()
    cols = ["ticker","title","yes_bid","yes_ask","no_bid","no_ask","volume","open_interest","close_time","event_ticker"]
    markets = [dict(zip(cols, r)) for r in rows]
    new_opps = []
    seen = state.get("seen_ev", {})
    for m in markets:
        yb, ya, nb, na = m["yes_bid"], m["yes_ask"], m["no_bid"], m["no_ask"]
        if not (yb and ya and nb and na):
            continue
        fair_yes, fair_no = remove_vig(yb, nb)
        ev_y = ev_yes(fair_yes, ya)
        ev_n = ev_no(fair_no, na)
        best_ev = max(ev_y, ev_n)
        if best_ev < MIN_EV:
            seen.pop(m["ticker"], None)
            continue
        side = "YES" if ev_y >= ev_n else "NO"
        price = ya if side == "YES" else na
        prob = fair_yes if side == "YES" else fair_no
        payout_mult = (100 - price) / price if price else 0
        kelly = kelly_fraction(prob, payout_mult)
        opp = {
            "ticker": m["ticker"],
            "title": (m.get("title") or "")[:70],
            "side": side,
            "price": price,
            "fair_prob": round(prob, 4),
            "ev_cents": round(best_ev * 100, 2),
            "kelly": round(kelly, 4),
            "volume": m["volume"],
            "detected_at": now_str()
        }
        prev_ev = seen.get(m["ticker"], {}).get("ev_cents", 0)
        if m["ticker"] not in seen or opp["ev_cents"] >= prev_ev + 1.0:
            new_opps.append(opp)
        seen[m["ticker"]] = opp
    state["seen_ev"] = seen
    return new_opps

def scan_flow(client, state):
    from src.common.db import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT ticker FROM markets WHERE status='open' AND volume>0 ORDER BY volume DESC LIMIT 20").fetchall()
    conn.close()
    tickers = [r[0] for r in rows]
    alerts = []
    seen = state.get("seen_flow", {})
    for ticker in tickers[:10]:
        try:
            resp = client.get_trades(ticker=ticker, limit=100)
            trades = resp.get("trades") or []
        except Exception:
            continue
        if len(trades) < 10:
            continue
        yes_vol = sum(t.get("count", 0) for t in trades if t.get("taker_side") == "yes")
        no_vol = sum(t.get("count", 0) for t in trades if t.get("taker_side") == "no")
        total = yes_vol + no_vol
        if total == 0:
            continue
        yes_pct = yes_vol / total
        large = [t for t in trades if (t.get("count") or 0) >= LARGE_TRADE]
        flow_alert = None
        if yes_pct > 0.80:
            flow_alert = {"ticker": ticker, "reason": "STRONG YES BUYING", "yes_pct": yes_pct, "total_vol": total}
        elif yes_pct < 0.20:
            flow_alert = {"ticker": ticker, "reason": "STRONG NO BUYING", "yes_pct": yes_pct, "total_vol": total}
        if large:
            biggest = max(large, key=lambda t: t.get("count", 0))
            flow_alert = {"ticker": ticker, "reason": "LARGE TRADE " + str(biggest["count"]) + " contracts " + (biggest.get("taker_side") or "?").upper(), "yes_pct": yes_pct, "total_vol": total}
        if flow_alert:
            key = ticker + ":" + flow_alert["reason"]
            last_seen = seen.get(key, 0)
            if time.time() - last_seen > 3600:
                flow_alert["detected_at"] = now_str()
                alerts.append(flow_alert)
                seen[key] = time.time()
    state["seen_flow"] = seen
    return alerts

def run_pass(client, state, run_num):
    log.info("=" * 60)
    log.info("Run #" + str(run_num) + " -- " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        n = refresh_markets(client)
        log.info("Markets refreshed: " + str(n) + " upserted")
    except Exception as e:
        log.warning("Market refresh failed: " + str(e))
    try:
        new_opps = scan_ev(state)
        if new_opps:
            log.info("EV scan: " + str(len(new_opps)) + " new opportunity(s)")
            for o in new_opps:
                msg = "[" + o["side"] + "] " + o["ticker"] + " | price=" + str(o["price"]) + "c fair=" + str(round(o["fair_prob"]*100,1)) + "% | EV=+" + str(o["ev_cents"]) + "c | kelly=" + str(round(o["kelly"]*100,1)) + "% | vol=" + str(o["volume"])
                alert("+EV: " + o["ticker"], msg)
        else:
            log.info("EV scan: no new opportunities")
    except Exception as e:
        log.warning("EV scan failed: " + str(e))
    try:
        flow_alerts = scan_flow(client, state)
        if flow_alerts:
            for fa in flow_alerts:
                msg = fa["ticker"] + " | " + fa["reason"] + " | yes_pct=" + str(round(fa["yes_pct"]*100)) + "% | vol=" + str(fa["total_vol"])
                alert("Flow: " + fa["ticker"], msg)
        else:
            log.info("Flow scan: no unusual activity")
    except Exception as e:
        log.warning("Flow scan failed: " + str(e))
    try:
        bal = client.get_balance()
        log.info("Balance: $" + str(round(bal.get("balance", 0)/100, 2)))
    except Exception:
        pass
    top_ev = sorted(state.get("seen_ev", {}).values(), key=lambda x: x.get("ev_cents", 0), reverse=True)[:20]
    (OUTPUT_DIR / "live_opportunities.json").write_text(json.dumps({"updated_at": now_str(), "opportunities": top_ev}, indent=2))
    state["runs"] = run_num
    state["last_run"] = now_str()
    save_state(state)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--min-ev", type=float, default=None)
    args = parser.parse_args()
    global MIN_EV
    if args.min_ev is not None:
        MIN_EV = args.min_ev
    from src.common.kalshi_client import KalshiClient
    client = KalshiClient()
    state = load_state()
    run_num = state.get("runs", 0)
    log.info("=" * 60)
    log.info("  Kalshi Autonomous Bot starting")
    log.info("  Interval: " + str(args.interval) + "s | Min EV: " + str(int(MIN_EV*100)) + "c | Watch: " + str(WATCH_SERIES or "all"))
    log.info("  Email alerts: " + ("yes -> " + ALERT_EMAIL_TO if ALERT_EMAIL_TO else "no"))
    log.info("=" * 60)
    if args.once:
        run_num += 1
        run_pass(client, state, run_num)
        return
    log.info("Running every " + str(args.interval) + "s. Ctrl+C to stop.\n")
    try:
        while True:
            run_num += 1
            try:
                run_pass(client, state, run_num)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log.error("Error in run #" + str(run_num) + ": " + str(e))
            log.info("Sleeping " + str(args.interval) + "s...\n")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("\nBot stopped.")
        save_state(state)

if __name__ == "__main__":
    main()
