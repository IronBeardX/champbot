# ChampBot

Air India-style airline chatbot built for the AI Champions AI Engineer (Junior) technical exercise.

Open <https://champbot.alejandroyeroval.workers.dev> in a browser for the chat UI, deployed on Cloudflare Python Workers.

## Repository layout

- `backend/`: FastAPI app, a self-contained [uv](https://docs.astral.sh/uv/) project.
- `backend/data/`: the policy corpus and the retrieval eval seed, outside `src/` so they are never bundled into the Worker.
- `frontend/`: the static chat UI, served by Workers Static Assets from `frontend/public`.
- `docs/architecture.md`: backend module layout and dependency rules.
- `docs/decisions.md`: technical decisions and the reasons behind them.

## Setup

Requirements:

- [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.13.7 or newer, the version that wrote `backend/uv.lock`. uv installs the pinned Python version (3.13) by itself.
- [Node.js](https://nodejs.org/), to run the frontend tests and to run on the Workers runtime or deploy. `pywrangler` calls `wrangler` through `npx`.

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

uvicorn only serves the JSON API; it does not serve the frontend. In a second terminal:

```sh
curl localhost:8000/health
curl localhost:8000/chat -H 'content-type: application/json' -d '{"message": "Can I change my flight?"}'
curl localhost:8000/chat -H 'content-type: application/json' -d '{"message": "And to Lisbon?", "history": [{"role": "user", "text": "Can I change my flight to Porto?"}, {"role": "assistant", "text": "Yes, you can change it online."}]}'
```

`POST /chat` sends `message` (1 to 2000 characters, not blank) plus an optional `history` of earlier turns, and returns `{"answer": "..."}`. The Worker keeps no state: it answers from exactly what the request sends, so the client must resend the whole conversation on every turn.

`history` is a list of `{"role": "user" | "assistant", "text": "..."}` items, defaulting to `[]`. It alternates roles starting with `user` and ending with `assistant`, since `message` is always the final user turn. `user` texts follow the same 1-2000 character rule as `message`; `assistant` texts must not be blank and are at most 8000 characters each, because answers (for example retrieved or appended by the server) can be longer than a user message. `history` holds at most 20 items and 40 000 characters in total. The client is responsible for trimming the oldest user/assistant pair once it nears these limits. Errors:

| Status | When | Body |
|---|---|---|
| 422 | `message` is missing, blank or longer than 2000 characters, or a `history` item has a missing/unknown role, or a blank/too-long text (2000 for `user`, 8000 for `assistant`) | FastAPI's list of validation errors in `detail` |
| 422 | `history` does not alternate `user`/`assistant` starting with `user`, does not end with an `assistant` turn, or has more than 20 items or more than 40 000 characters in total | FastAPI's list of validation errors in `detail` |
| 429 | Gemini rate-limits the request. `Retry-After` is set when Gemini gives a delay, capped at one hour | Fixed message in `detail` |
| 502 | Gemini fails or returns no usable answer | Fixed message in `detail` |
| 504 | Gemini does not answer within 25 seconds | Fixed message in `detail` |
| 500 | Configuration error: `GEMINI_API_KEY` or `GEMINI_MODEL` is missing; the server log names the variable. Other unexpected errors return Starlette's plain-text 500 | Fixed message in `detail` |

### On the Workers runtime

Runs the app the way it runs in production: on Pyodide, through the Workers ASGI adapter, with Workers Static Assets serving the frontend. This is the full local stack, including the chat UI; it is slower to start than uvicorn, so use it to check platform behavior, not for day-to-day backend development.

```sh
cd backend
uv run pywrangler dev --env-file ../.env
```

Open <http://localhost:8787> for the chat UI. In a second terminal:

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

```sh
cd frontend
npm test
```

## Policy corpus

Air India policy pages, used for retrieval-augmented `/chat` answers, live as Markdown in `backend/data/policies/`. They were copied by hand from the live [airindia.com](https://www.airindia.com) site on 2026-11-04: the site is JS-rendered, so an automated fetch sees an empty shell, and no scraper was written. Each file's front matter keeps its `title`, `source_url` and `retrieved_at`.

| File | Source |
|---|---|
| `checked-and-cabin-baggage.md` | [Checked Baggage Allowance](https://www.airindia.com/in/en/travel-information/baggage-guidelines/checked-baggage-allowance.html), [Cabin Baggage](https://www.airindia.com/in/en/travel-information/baggage-guidelines/cabin-baggage.html) |
| `baggage-faq.md` | [Baggage FAQs](https://www.airindia.com/in/en/frequently-asked-questions/baggage.html) |
| `check-in.md` | [Check-in FAQs](https://www.airindia.com/in/en/frequently-asked-questions/check-in.html) |
| `cancellation-and-refund.md` | [Payment, Refund, and Cancellations FAQ](https://www.airindia.com/in/en/frequently-asked-questions/payment-refund-cancellations.html) |
| `special-assistance.md` | [Health and Medical Assistance](https://www.airindia.com/in/en/frequently-asked-questions/health-and-medical-assistance.html) |
| `infants-and-pregnancy.md` | [Expectant Mothers and Infants Travel Guidelines](https://www.airindia.com/in/en/travel-information/first-time-flyers/expected-mothers-infants.html) |
| `delayed-and-lost-baggage.md` | [Lost and Damaged Baggage Information and Support](https://www.airindia.com/in/en/travel-information/baggage-guidelines/lost-damaged-baggage.html) |

This content is © Air India Limited, condensed and reformatted for this non-commercial technical exercise. It may be out of date, and ChampBot is not affiliated with or endorsed by Air India.

`backend/data/eval/policy_questions.json` has a small seed of policy questions and off-topic queries, used later to calibrate retrieval (IRO-181, IRO-189).

Split the corpus into chunks and check the result against Vectorize's id and metadata limits:

```sh
cd backend
uv run champbot-ingest --dry-run
```
