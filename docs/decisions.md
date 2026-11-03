# Decision log

Every meaningful technical decision, newest last. Each entry records the context, the decision, the alternatives that were considered and its consequences.

## 1. Free tiers only

- **Context**: ChampBot is a technical exercise and a public demo. It has no budget, and the owner will not attach a payment method to any provider.
- **Decision**: every service the project uses must run on a free tier that requires no card on file.
- **Alternatives**: paid tiers or trials that ask for a card, rejected by the constraint itself.
- **Consequences**: this constraint drives most of the decisions below. Rate limits and quotas of free tiers become design inputs (prompt size, embedding volume, caching).

## 2. Python + FastAPI for the backend

- **Context**: the backend serves a chat API with streaming, a retrieval pipeline and the static frontend.
- **Decision**: Python with FastAPI.
- **Alternatives**: none seriously considered. Python has the strongest LLM and RAG ecosystem, and FastAPI gives typed request handling, async support and streaming responses out of the box.
- **Consequences**: the hosting platform must run Python (see 4).

## 3. Google Gemini Flash as LLM, behind a provider interface

- **Context**: the chatbot needs an LLM that is free and has enough throughput for RAG prompts, which carry retrieved context and are large.
- **Decision**: Google Gemini Flash on its free tier, called through a small provider interface owned by the project so the model or provider can be swapped.
- **Alternatives**:
  - Claude: its API is billed separately from the claude.ai plan, which breaks decision 1.
  - Groq: 12K tokens per minute on the free tier is too low for RAG prompts.
  - Workers AI LLMs: weaker models, and they share the 10K daily neurons with embeddings (see 6).
- **Consequences**: application code depends on the interface, not on the Gemini SDK, and tests use a fake provider. Gemini free-tier rate limits apply.

## 4. Cloudflare Python Workers for hosting

- **Context**: the app must be deployed publicly for free.
- **Decision**: Cloudflare Python Workers on the free plan.
- **Alternatives**: Cloudflare Containers, rejected because they are paid only.
- **Consequences**: Python Workers run on Pyodide (CPython compiled to WebAssembly), so every dependency must be pure Python or available for Pyodide, and the free plan's CPU limit per request applies. The Python version is pinned to 3.12; it must be revalidated against the Pyodide version the Workers runtime ships when the deployment is set up (IRO-159). Superseded by decision 10, which settles on Python 3.13.

## 5. Cloudflare Vectorize as vector database

- **Context**: retrieval needs a vector store reachable from the hosting platform.
- **Decision**: Cloudflare Vectorize on its free tier.
- **Alternatives**: none seriously considered. It lives on the same platform as the Worker, so it needs no extra account, credentials or network hop.
- **Consequences**: the free-tier limits on stored vectors and queries bound the size of the knowledge base.

## 6. Workers AI `bge-m3` for embeddings

- **Context**: documents and queries must be embedded for retrieval, and users may write in more than one language.
- **Decision**: the `bge-m3` model on Workers AI.
- **Alternatives**: Voyage, rejected because its rate limits without a payment method are too low.
- **Consequences**: `bge-m3` is multilingual, so queries and documents do not need to share a language. Embedding calls consume the Workers AI daily neuron quota.

## 7. Plain HTML + JS frontend with SSE streaming

- **Context**: the demo needs a simple chat UI that shows answers as they are generated.
- **Decision**: plain HTML and JavaScript, served as static files by FastAPI, with answers streamed over Server-Sent Events.
- **Alternatives**: none seriously considered.
- **Consequences**: one deployable unit. SSE is one-directional (server to client), which is all a chat answer stream needs.

## 8. Tooling: uv, ruff, pyright, pytest

- **Context**: the project needs dependency management, linting, formatting, type checking and tests, all enforced in CI.
- **Decision**: uv for Python and dependency management, ruff for lint and format, pyright in strict mode for types, pytest for tests.
- **Alternatives**: mypy instead of pyright, rejected because pyright is faster, and its strict mode, which this project enables, catches more issues than mypy's strict mode.
- **Consequences**: `uv.lock` is committed and CI installs with `uv sync --locked`, so CI fails if the lockfile is out of date.

## 9. Monorepo with `backend/` and `frontend/`

- **Context**: the repository holds the Python backend and the static frontend.
- **Decision**: one repository with two top-level folders. `backend/` is a self-contained uv project; `frontend/` holds the static files.
- **Alternatives**:
  - A single uv project at the root: mixes Python tooling with the frontend.
  - A uv workspace with `backend` as a member: only useful with several Python packages.
- **Consequences**: backend commands run from `backend/`, and CI sets that as its working directory.

## 10. Python Workers deployment: Python 3.13 and pywrangler

- **Context**: decision 4 left the Python version to revalidate against the Workers runtime, and the app had to be packaged for Pyodide and deployed.
- **Decision**:
  - Python 3.13 locally, in CI and in the Worker. The runtime picks the Python version from the compatibility date: dates from 2026-09-08 run 3.14, earlier ones 3.13. `compatibility_date` is pinned to 2026-09-07 to stay on 3.13, preferred for its longer time in production on Workers.
  - `pywrangler` (from `workers-py`) as a dev dependency. It vendors the runtime dependencies from `pyproject.toml` for Pyodide and proxies every other command to `wrangler`.
  - The Workers entrypoint lives in `backend/src/worker.py`, outside the `champbot` package, and only wraps the FastAPI app with `workers.asgi.entrypoint`. The package never imports `workers`, which only exists inside the runtime.
- **Alternatives**:
  - Python 3.14, the runtime default for current dates: discarded in favor of the more established 3.13.
  - Plain `wrangler` with hand-vendored packages: a second dependency list to keep in sync with `pyproject.toml`.
  - The entrypoint inside the `champbot` package: mixes platform glue into application code.
- **Consequences**:
  - `pywrangler` requires uv 0.13.4 or newer, and Node.js for `npx wrangler`.
  - Moving to Python 3.14 later means bumping the compatibility date and `requires-python` together.
  - Measured on the first deploy of the `/health`-only app: 8.3 MiB uploaded (2.1 MiB gzipped), almost all of it vendored FastAPI and Pydantic. The first request after the deploy took about 6.5 s, and warm requests about 0.7 s end to end.
  - **Free plan limits exceeded, risk accepted by the owner.** Wrangler reported a Worker startup time of 2395 ms against the documented 1 s limit, and the deploy was still accepted. The dashboard showed a CPU time per request of 11.67 ms median and 28.43 ms p99 against the 10 ms limit, while every request still returned 200. Cloudflare does not document how much it tolerates over these limits, so heavier endpoints or sustained traffic may start failing with error 1102 ("Worker exceeded resource limits"). The owner chose to keep building on Python Workers: the application code does not depend on the host, so a later move to another host keeps it. Watch for 1102 errors and for CPU time growing as endpoints are added.

## 11. Continuous deployment from the CI workflow

- **Context**: the public demo must always serve the code on `main`, without depending on someone deploying by hand.
- **Decision**:
  - A `deploy` job in `.github/workflows/ci.yml` runs `pywrangler deploy` after the `backend` checks pass, only on pushes to `main`.
  - The job uses only the `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` repository secrets. Runtime secrets stay in Cloudflare and the workflow never sets them.
  - Each deployment is tagged with the commit SHA (`--message`), and the job runs in the `production` GitHub environment, which links the live URL to each deployed commit.
  - The job is in a concurrency group without cancellation, so deploys run one at a time.
- **Alternatives**:
  - A separate workflow triggered by `workflow_run`: it always runs from the default branch, has to check out the tested commit by hand and is not linked to the commit's checks.
  - `cloudflare/wrangler-action`: it runs plain `wrangler`, which does not vendor the Python dependencies (see 10).
  - Cloudflare Workers Builds: it cannot wait for the CI checks, and the pipeline would live outside the repository.
- **Consequences**:
  - A concurrency group keeps one running and one pending job. A newer push cancels a pending deploy, so a commit merged while another deploy is running can skip its own deploy, and its CI run shows as cancelled. Its code still goes live with the newer commit. Without the group, two deploys could overlap and an older one could finish last and leave stale code live.
  - `pywrangler` runs `npx --yes wrangler`, so CI always uses the latest wrangler, the same as a manual deploy. Pinning it was left out of scope, so a breaking wrangler release would break deploys until it is pinned.
