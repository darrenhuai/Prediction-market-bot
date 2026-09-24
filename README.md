# Prediction Market Bot

[![CI](https://github.com/darrenhuai/prediction-market-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/darrenhuai/prediction-market-bot/actions/workflows/ci.yml)

Prediction Market Bot is a Python research framework for collecting prediction-market data, running analyses, and experimenting with positive expected value (EV) market signals.

The project is currently focused on personal research workflows around Kalshi and Polymarket data. It can be extended to send alerts when a positive EV trade appears and can be adapted for automated trading experiments.

## Quick start: the web app

You need [uv](https://docs.astral.sh/uv/) installed. Then:

```bash
uv sync
uv run app.py --open        # live Kalshi markets at http://localhost:8000
uv run app.py --demo --open # made-up data, no internet or Kalshi account needed
```

The app has four tabs:

- **Opportunities**: things worth a look right now, in plain English.
  - *Your picks with an edge*: markets where the price beats the chance **you** gave them, after Kalshi's fees.
  - *Arbitrage*: groups of outcomes where only one can happen, priced so buying all of them costs less than you get back. Only ones marked **Locked in** can't lose.
  - *Unusual activity*: very one-sided buying or very large trades in the busiest markets.
- **Markets**: search every open Kalshi market. Tap one, enter the chance you think it has, and the app shows the expected profit or loss for buying YES or NO, plus a suggested stake.
- **My picks**: the estimates you've saved. They're re-checked on every refresh.
- **Settings**: bankroll (for stake sizing), minimum edge, refresh interval, and more.

To let other people on your network use it, run `uv run app.py --host 0.0.0.0` and share `http://<your-computer's-IP>:8000`. There's no login, so only do this on a network you trust.

The app never places trades. Reading market data doesn't need a Kalshi account.

### Settings and your Kalshi account (optional)

Put these in a file called `.env` in the project folder. All of them are optional.

| Variable | What it does |
| --- | --- |
| `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH` | Your Kalshi API key (RSA or Ed25519), to show your balance. Create one in Kalshi's account settings. Save the key file **outside** this folder, or name it `*.key` or `*.pem` so git ignores it. |
| `ALERT_EMAIL_TO`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_PASSWORD` | Email alerts. `ALERT_SMTP_HOST` / `ALERT_SMTP_PORT` default to Gmail. |
| `BANKROLL` | Money you're willing to bet, for stake suggestions (default 0: off). |
| `MIN_EV_THRESHOLD` | Smallest edge worth showing, in dollars per contract (default 0.02 = 2¢). |
| `BOT_INTERVAL_SECONDS` | Time between scans (default 300). |
| `LARGE_TRADE_THRESHOLD` | Smallest trade counted as "large" (default 50 contracts). |
| `WATCH_SERIES` | Only scan these series, e.g. `KXFED,KXHIGHNY` (default: everything). |
| `KALSHI_FEE_RATE` | Kalshi's fee rate (default 0.07). |

Anything you change on the app's **Settings** tab overrides the `.env` value, and is saved in `data/settings.json`.

### Running without the UI

`bot.py` does the same scan on a timer. It logs to `output/alerts.log` and can email you (see the email settings above). It uses the same picks and settings as the web app, re-reading them on every scan, so you can run both at once.

```bash
uv run bot.py                # scan every 5 minutes
uv run bot.py --once --list  # one scan, print everything it found
uv run bot.py --demo --list  # same, on demo data
```

### Why "your own estimate"?

The first version of this bot compared a market's "fair" price, worked out from its own bids, with that same market's asks. That number is always zero or negative, so it could never find anything. A market can't tell you it's mispriced; you need an outside view. That view is either your own probability or a guaranteed-payout comparison (arbitrage). Estimates, settings and cached market data are saved in `data/`, which is kept out of git.

## What this repo does

- Loads indexers that collect market data
- Runs reusable analysis classes from `src/analysis`
- Saves analysis outputs to local files such as CSV and JSON
- Provides a small CLI entry point through `main.py`
- Keeps credentials out of source control with `.env` configuration

## Development

```bash
uv sync --all-groups   # install runtime + dev dependencies
uv run ruff check .    # lint
uv run pytest          # run the test suite
```

CI runs both commands on every push and pull request to `main` (see `.github/workflows/ci.yml`).

## Current status

This repo is an experimental research framework, not a production trading system. Any strategy should be validated carefully before real money is involved.
