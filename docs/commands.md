# Commands

## Web app and live scanner

```bash
uv run app.py [--demo] [--host 0.0.0.0] [--port 8000] [--open]
uv run bot.py [--demo] [--once] [--list] [--interval SECONDS] [--min-ev DOLLARS]
```

`app.py` serves the UI in `web/`, and `bot.py` runs the same scanner (`src/scanner/`) without a UI.

## Research CLI

The research tools are run through `main.py`.

## Analyze

Run the interactive analysis picker:

```bash
uv run main.py analyze
```

Run a specific analysis by name:

```bash
uv run main.py analyze <analysis_name>
```

Analysis outputs are written to the `output/` directory.

## Index

Run the interactive indexer picker:

```bash
uv run main.py index
```

Run a specific indexer by name:

```bash
uv run main.py index <indexer_name>
```

Indexers may require local environment variables, API credentials, or RPC endpoints depending on the data source.

## Development checks

Run lint checks:

```bash
uv run ruff check .
```

Run tests:

```bash
uv run pytest
```
