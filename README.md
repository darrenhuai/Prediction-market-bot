# Prediction Market Bot

Prediction Market Bot is a Python research framework for collecting prediction-market data, running analyses, and experimenting with positive expected value (EV) market signals.

The project is currently focused on personal research workflows around Kalshi and Polymarket data. It can be extended to send alerts when a positive EV trade appears and can be adapted for automated trading experiments.

## What this repo does

- Loads indexers that collect market data
- Runs reusable analysis classes from `src/analysis`
- Saves analysis outputs to local files such as CSV and JSON
- Provides a small CLI entry point through `main.py`
- Keeps credentials out of source control with `.env` configuration

## Current status

This repo is an experimental research framework, not a production trading system. Any strategy should be validated carefully before real money is involved.
