# Roadmap

This roadmap tracks practical improvements for turning the repository into a stronger research and engineering portfolio project.

## Near term

- Add tests for CLI helper functions.
- Improve README setup instructions.
- Add examples for running one indexer and one analysis.
- Document required environment variables for each data source.
- Add sample outputs using non-sensitive mock data.

## Research improvements

- Compare market prices against model-implied probabilities.
- Track historical edge decay after alerts are generated.
- Add liquidity and spread filters before flagging opportunities.
- Create dashboards for realized vs expected performance.

## Engineering improvements

- Add CI for linting and tests.
- Add structured logging for indexer runs.
- Add retry and backoff behavior around external API calls.
- Separate research notebooks from reusable library code.

## Safety and risk controls

- Keep automated trading disabled by default.
- Require explicit confirmation before any order placement workflow.
- Log all decisions and inputs used for potential trades.
- Add position sizing and exposure limits before live execution.
