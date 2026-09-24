"""Headless Kalshi scanner: refreshes markets on a timer and logs/emails new opportunities.

    uv run bot.py            # run forever, every BOT_INTERVAL_SECONDS (default 5 min)
    uv run bot.py --once     # one scan, then exit
    uv run bot.py --demo     # use made-up data (no network or account needed)

Add your own probability estimates in the web app (uv run app.py). The bot
re-reads the same data/ files on every scan and alerts when a price gives you
an edge. Settings come from .env unless you've changed them in the web app.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.scanner.alerts import describe  # noqa: E402
from src.scanner.service import SETTING_BOUNDS, Scanner, validate_setting  # noqa: E402

log = logging.getLogger("kalshi-bot")


def setup_logging(log_file: Path = Path("output/alerts.log")) -> None:
    log_file.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)],
    )


def make_scanner(demo: bool) -> Scanner:
    if demo:
        from src.scanner.demo import DemoSource
        return Scanner(DemoSource(), mode="demo")
    from src.common.kalshi_client import KalshiClient
    return Scanner(KalshiClient(), mode="live")


def run_pass(scanner: Scanner) -> None:
    scanner.refresh()
    if scanner.snapshot.get("error"):
        log.warning(scanner.snapshot["error"])
        return
    opps = scanner.opportunities()
    log.info("Found %d pick(s), %d arbitrage, %d unusual activity",
             len(opps["picks"]), len(opps["arbitrage"]), len(opps["flow"]))
    scanner.alerter.send(scanner.all_opportunities())
    if scanner.snapshot.get("balance") is not None:
        log.info("Balance: $%.2f", scanner.snapshot["balance"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=int, default=None, help="seconds between scans")
    parser.add_argument("--once", action="store_true", help="run one scan and exit")
    parser.add_argument("--min-ev", type=float, default=None, help="minimum edge in dollars per contract, e.g. 0.02")
    parser.add_argument("--demo", action="store_true", help="use made-up demo data")
    parser.add_argument("--list", action="store_true", help="print every current opportunity, even ones already alerted")
    args = parser.parse_args()

    setup_logging()
    scanner = make_scanner(args.demo)
    if args.min_ev is not None:
        try:
            scanner.overrides["min_edge_cents"] = validate_setting("min_edge_cents", args.min_ev * 100)
        except ValueError as e:
            parser.error(f"--min-ev: {e}")
        scanner.reload()
    max_interval = int(SETTING_BOUNDS["refresh_minutes"][1] * 60)
    interval = min(max(1, args.interval or int(scanner.settings["refresh_minutes"] * 60)), max_interval)
    s = scanner.settings
    log.info("Kalshi bot starting (%s) | every %ds | min edge %.1fc | %d pick(s) saved",
             scanner.mode, interval, s["min_edge_cents"], len(scanner.estimates))

    if args.once or args.list:
        run_pass(scanner)
        if args.list:
            for opp in scanner.all_opportunities():
                title, body = describe(opp)
                print(f"\n* {title}\n  " + body.replace("\n", "\n  "))
        return
    try:
        while True:
            try:
                run_pass(scanner)
            except Exception as e:
                log.error("Scan failed: %s", e)
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Bot stopped.")


if __name__ == "__main__":
    main()
