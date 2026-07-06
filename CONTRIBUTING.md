# Contributing

Thanks for checking out this project. This repository is currently a personal research framework, but contributions and suggestions are welcome.

## Local setup

1. Clone the repository.
2. Install dependencies with `uv sync`.
3. Copy `.env.example` to `.env` and fill in any local credentials or RPC endpoints.
4. Run commands through `uv run` so the project environment is used consistently.

## Development workflow

- Keep commits focused and descriptive.
- Avoid committing credentials, API keys, exported data, or generated outputs.
- Prefer adding tests when changing reusable utilities or analysis logic.
- Use clear names for new indexers and analyses so they appear cleanly in the CLI menu.

## Code quality

Before opening a pull request or merging changes, run:

```bash
uv run ruff check .
uv run pytest
```

Some workflows may require credentials or external APIs, so document any setup requirements in the relevant file or README section.
