# ChampBot

Air India-style airline chatbot built for the AI Champions AI Engineer (Junior) technical exercise.

Live at <https://champbot.alejandroyeroval.workers.dev>, deployed on Cloudflare Python Workers.

## Repository layout

- `backend/`: FastAPI app, a self-contained [uv](https://docs.astral.sh/uv/) project.
- `frontend/`: will hold the static chat UI, served by Workers Static Assets.
- `docs/architecture.md`: backend module layout and dependency rules.
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
uv run uvicorn champbot.main:app --reload --env-file ../.env
```

In a second terminal:

```sh
curl localhost:8000/health
curl localhost:8000/chat -H 'content-type: application/json' -d '{"message": "Can I change my flight?"}'
```

`POST /chat` sends a single message (1 to 2000 characters) to the LLM and returns `{"answer": "..."}`. Errors:

| Status | When | Body |
|---|---|---|
| 422 | The message is missing, blank or longer than 2000 characters | FastAPI's list of validation errors in `detail` |
| 429 | Gemini rate-limits the request. `Retry-After` is set when Gemini gives a delay, capped at one hour | Fixed message in `detail` |
| 502 | Gemini fails or returns no usable answer | Fixed message in `detail` |
| 504 | Gemini does not answer within 25 seconds | Fixed message in `detail` |
| 500 | Configuration error: `GEMINI_API_KEY` or `GEMINI_MODEL` is missing; the server log names the variable. Other unexpected errors return Starlette's plain-text 500 | Fixed message in `detail` |

### On the Workers runtime

Runs the app the way it runs in production: on Pyodide, through the Workers ASGI adapter. Slower to start than uvicorn, so use it to check platform behavior, not for day-to-day development.

```sh
cd backend
uv run pywrangler dev --env-file ../.env
```

In a second terminal:

```sh
curl localhost:8787/health
curl localhost:8787/chat -H 'content-type: application/json' -d '{"message": "Can I change my flight?"}'
```

## Deploy

Every push to `main` deploys to <https://champbot.alejandroyeroval.workers.dev> automatically. The `deploy` job in CI runs after the checks pass. Deploys never overlap, and a newer push replaces a deploy still waiting to start. Each Cloudflare deployment is tagged with its commit SHA, so you can see which commit is live:

```sh
cd backend
uv run pywrangler deployments list
```

The job only uses the `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` repository secrets. Runtime secrets live in Cloudflare and are set with `uv run pywrangler secret put <NAME>`. The Worker needs one:

```sh
cd backend
uv run pywrangler secret put GEMINI_API_KEY
```

The model id is a plain variable in `backend/wrangler.jsonc`, deployed with the code.

To deploy by hand, log in to Cloudflare once with `uv run pywrangler login`, then:

```sh
cd backend
uv run pywrangler deploy
```

`pywrangler` vendors the runtime dependencies from `pyproject.toml` for Pyodide and uploads them with the Worker. Check the result with:

```sh
curl https://champbot.alejandroyeroval.workers.dev/health
curl https://champbot.alejandroyeroval.workers.dev/chat -H 'content-type: application/json' -d '{"message": "Can I change my flight?"}'
```

### Preview deployments

Every pull request from an `iro-<n>-...` branch gets a preview of its code at `https://iro-<n>-champbot.alejandroyeroval.workers.dev`. The `preview` job in CI uploads the branch head as a new Worker version once the checks pass, without deploying it, so production keeps serving `main`. The job keeps one comment on the pull request with the preview URL and the commit it was built from, and updates it on every push. Branches without the `iro-<n>-` prefix get no preview, and the job shows as skipped.

Previews use the production secrets, so `/chat` on a preview spends the same Gemini quota. They are public, like the production URL. `wrangler tail` and Workers Logs do not see their requests.

## Checks

The same checks run in CI on every pull request and on pushes to `main`.

```sh
cd backend
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run lint-imports
uv run pytest
```
