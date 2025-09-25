# Repository Guidelines

## Project Structure & Module Organization
- `src/smolagents/`: core library (agents, tools, models, executors, CLI). Prompts live in `src/smolagents/prompts/`.
- `tests/`: pytest suite (`test_*.py`, mirrors package layout). Fixtures in `tests/fixtures/`.
- `examples/`: runnable demos. Execute with `python examples/<name>.py`.
- `docs/`: project docs; keep examples and API references in sync.

## Build, Test, and Development Commands
- Environment: `pip install -e ".[dev]"` to install with dev/test extras.
- Lint/format check: `make quality` (ruff check + format check).
- Auto-fix style: `make style` (ruff --fix + format).
- Run tests: `make test` or `pytest -q` (filter: `pytest -k <expr>`).
- CLI smoke test: `smolagent --help` or `python -m smolagents.cli`.

## Coding Style & Naming Conventions
- Python ≥ 3.10, 4-space indent, type hints required for public APIs.
- Ruff enforces style and formatting; line length is 119; imports are sorted.
- Naming: modules/files `snake_case`; classes `PascalCase`; functions/vars `snake_case`; constants `UPPER_SNAKE_CASE`.
- Be Pythonic and OOP-first: small, composable classes; avoid side effects in tools/agents; add docstrings for public members.

## Testing Guidelines
- Framework: `pytest`. Place tests under `tests/` as `test_*.py` and mirror package structure.
- Write unit tests for all new functionality and bug fixes; prefer deterministic tests (mock network/IO).
- Aim for meaningful coverage on new/changed code; add regression tests for reported issues.

## Commit & Pull Request Guidelines
- Use Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` with optional scope (e.g., `feat(cli): ...`).
- Commits: imperative mood, concise; reference issues (`#123`) when relevant.
- PRs: clear description, linked issues, before/after notes; include tests and update docs/examples when behavior changes.
- Ensure `make quality` and `make test` pass; run `pre-commit install` locally.

## Security & Configuration Tips
- Put secrets in `.env`; never commit secrets. The project uses `python-dotenv` in examples.
- Prefer configuration via environment variables; avoid hardcoding keys in examples or tests.
