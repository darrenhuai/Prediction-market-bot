# Prediction Market Bot

[![CI](https://github.com/darrenhuai/prediction-market-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/darrenhuai/prediction-market-bot/actions/workflows/ci.yml)

Prediction Market Bot is a Python research framework for collecting prediction-market data, running analyses, and experimenting with positive expected value (EV) market signals.

The project is currently focused on personal research workflows around Kalshi and Polymarket data. It can be extended to send alerts when a positive EV trade appears and can be adapted for automated trading experiments.

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
