# ChampBot

Air India-style airline chatbot built for the AI Champions AI Engineer (Junior) technical exercise.

## Repository layout

- `backend/`: FastAPI app, a self-contained [uv](https://docs.astral.sh/uv/) project.
- `frontend/`: will hold the static chat UI served by the backend.
- `docs/decisions.md`: technical decisions and the reasons behind them.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the pinned Python version (3.13) by itself.

```sh
cd backend
uv sync
```

## Run

```sh
cd backend
uv run uvicorn champbot.main:app --reload
```

In a second terminal:

```sh
curl localhost:8000/health
```

## Checks

The same checks run in CI on every pull request and on pushes to `main`.

```sh
cd backend
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```
