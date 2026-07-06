# Architecture

This project is organized around two reusable concepts: indexers and analyses.

## Indexers

Indexers live under `src/indexers` and inherit from `src.common.indexer.Indexer`. Their job is to collect or refresh data from external sources such as prediction-market APIs, RPC endpoints, or local data exports.

The CLI discovers indexers dynamically, which makes it easy to add a new data source without modifying the command menu directly.

## Analyses

Analyses live under `src/analysis` and inherit from `src.common.analysis.Analysis`. Each analysis implements a `run()` method that returns an `AnalysisOutput` object.

An analysis can return:

- a Matplotlib figure or animation
- a pandas DataFrame
- a chart configuration
- metadata for downstream use

## Output flow

The `Analysis.save()` method writes supported outputs to the `output/` directory. Supported output formats include CSV, JSON, PNG, PDF, SVG, and GIF depending on what the analysis returns.

## CLI entry point

`main.py` provides two primary commands:

```bash
uv run main.py index
uv run main.py analyze
```

Both commands can be run interactively or with a specific indexer or analysis name.
