# ChampBot

Air India-style airline chatbot built for the AI Champions AI Engineer (Junior) technical exercise.

Live at <https://champbot.alejandroyeroval.workers.dev>, deployed on Cloudflare Python Workers.

## Repository layout

- `backend/`: FastAPI app, a self-contained [uv](https://docs.astral.sh/uv/) project.
- `frontend/`: will hold the static chat UI served by the backend.
- `docs/decisions.md`: technical decisions and the reasons behind them.

## Setup

Requirements:

- [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.13.7 or newer, the version that wrote `backend/uv.lock`. uv installs the pinned Python version (3.13) by itself.
- [Node.js](https://nodejs.org/), only to run on the Workers runtime or deploy. `pywrangler` calls `wrangler` through `npx`.

```sh
cd backend
uv sync
```

Copy `.env.example` to `.env` at the repository root; it lists every required variable.

## Run

```sh
cd backend
uv run uvicorn champbot.main:app --reload
```

In a second terminal:

```sh
curl localhost:8000/health
```

### On the Workers runtime

Runs the app the way it runs in production: on Pyodide, through the Workers ASGI adapter. Slower to start than uvicorn, so use it to check platform behavior, not for day-to-day development.

```sh
cd backend
uv run pywrangler dev
```

In a second terminal:

```sh
curl localhost:8787/health
```

## Deploy

Deploys are manual for now. Log in to Cloudflare once with `uv run pywrangler login`, then:

```sh
cd backend
uv run pywrangler deploy
```

`pywrangler` vendors the runtime dependencies from `pyproject.toml` for Pyodide and uploads them with the Worker. Check the result with:

```sh
curl https://champbot.alejandroyeroval.workers.dev/health
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
