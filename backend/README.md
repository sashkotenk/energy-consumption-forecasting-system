# EnergyForecast backend

Install the locked development environment and run the baseline checks:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

The package uses a `src` layout. Business modules are introduced by later implementation tasks.
