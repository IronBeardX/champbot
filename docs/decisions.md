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

## 7. Plain HTML + JS frontend, served by Workers Static Assets

- **Context**: the demo needs a simple chat UI. The initial version streamed answers over SSE, served as static files by FastAPI.
- **Decision**: plain HTML and JavaScript, served from the same origin by Workers Static Assets (`backend/wrangler.jsonc`'s `assets.directory` points at `frontend/public`), not by FastAPI. Requests that match a static file are served without reaching the Worker; everything else, including unknown paths, falls through to it. Answers are rendered with `textContent` only, never `innerHTML`. The status-to-message mapping (`frontend/public/reply.js`) is unit tested with Node's built-in `node:test`, with no dependencies. A single turn is the whole interaction: the UI sends one message and renders one answer, with no streaming.
- **Alternatives**:
  - FastAPI serving the static files: every page load would cost Worker CPU time, which is scarce on the free plan (decision 10).
  - SSE streaming: deferred to the Bonus scope. It adds a second endpoint and a client-side event parser for a demo whose answers are short.
- **Consequences**: one deployable unit, same origin, so no CORS. The frontend has its own lightweight check in CI (`frontend` job, `node --test`) instead of pulling in a browser-testing dependency. The DOM glue in `app.js` and the wrangler config have no unit tests of their own; they are checked by hand on `pywrangler dev` and on the pull request preview.

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

## 12. Gemini through its REST API over httpx

- **Context**: decision 3 put Gemini behind a provider interface. The Google Gen AI SDK (`google-genai`) is the official client, but every runtime dependency must work on Pyodide (decision 4), and the issue asked to validate it there with the REST API as fallback.
- **Decision**: `GeminiProvider` calls the `generateContent` REST endpoint directly with an async `httpx` client, a 25 s deadline for the whole request and the key in the `x-goog-api-key` header.
- **Alternatives**: the Google Gen AI SDK. Rejected because it cannot be installed for the Worker: `google-genai` 2.34.0 requires `pydantic>=2.12.5`, while the Pyodide bundle only has wheels for `pydantic` 2.10.6 (`pydantic-core` 2.27.2), so `pywrangler` fails to resolve the dependencies. It would also add `google-auth`, `requests`, `websockets` and `tenacity` to a bundle that already exceeds the startup limit.
- **Consequences**:
  - The provider maps HTTP failures to the interface errors itself: timeout, 429 with the delay from `RetryInfo.retryDelay` (rounded up and capped at one hour), any other error or a response without text.
  - Gemini thinking models return their reasoning as extra parts flagged with `thought`, which the provider skips.
  - httpx timeouts apply to each phase of a request, so the provider also wraps the request in `asyncio.timeout` to bound it as a whole. Checked on `pywrangler dev`: httpx works on Pyodide, both timeouts are honored, and a network failure such as an unknown host surfaces as `httpx.ConnectError`, which maps to 502 like any other transport error. `httpx` adds about 0.3 MiB to the upload (8.6 MiB, 2.2 MiB gzipped). The Worker startup time with `httpx` was not measured.
  - Provider errors carry only Gemini's codes: `finishReason` and `blockReason` for a response without an answer, and the HTTP code plus `error.status` for an error response. Each code is checked against an upper-case code pattern before it is logged. Neither model output nor error bodies, which can quote the user's message, reach the logs. Transport failures are logged through the httpx exception repr, which holds the exception type and message but not request headers or bodies. The guarantee depends on that staying true.
  - The application runs on `pydantic` 2.14 locally and 2.10 on Workers, so the code must stay within what 2.10 supports.
  - Observed latency is high: 3 to 22 s for a one-sentence answer from `gemini-3.6-flash`. On the test day `gemini-3.8-flash`, the newest Flash, answered 503 ("high demand") or did not answer within 25 s on every request, locally and in production, so the default model is `gemini-3.6-flash`. Moving to a newer model is a change to `GEMINI_MODEL` only.
  - Availability is uneven on the free tier: in one production session, 3 of 6 requests to `gemini-3.6-flash` hit the 25 s timeout and others got 503. All of them mapped to 504 and 502 as designed.
  - CPU time per request in production, read from the `cpuTime` field of `wrangler tail` on 2026-11-03: `/chat` 25 to 207 ms over 8 requests, median about 104 ms; `/health` 30 to 113 ms over 6 requests, median about 48 ms. Every request is far above the 10 ms Free plan limit, and Cloudflare still reported `outcome: ok`, the same tolerance seen in decision 10. A burst of 12 `/health` requests showed the split: requests served by an already-warm isolate took 10 to 19 ms, and requests that landed on a new isolate took 40 to 140 ms, so most of the earlier samples were cold starts spread over several colos. `/chat` never went below about 72 ms. Waiting for Gemini adds wall time, not CPU time, so the extra cost is in the request handling itself. One candidate is the `httpx.AsyncClient` built for every request: creating it costs about 25 ms of CPU the first time and 3 ms afterwards on native CPython, and more on Pyodide. This endpoint increases the error 1102 risk accepted in decision 10. IRO-164 follows up on reducing it and on measuring the startup time.

## 13. Runtime configuration and the `/chat` error contract

- **Context**: `/chat` needs the Gemini key and model id both under uvicorn and on Workers, and it must report LLM failures without leaking internals.
- **Decision**:
  - One loader builds `Settings` from the Workers `env` binding (`request.scope["env"]`) when present, and from `os.environ` otherwise. A missing value raises an error that names the variable, never its value. That name only goes to the log, and `/chat` answers a generic JSON 500 with the same `{"detail": ...}` shape as every other error.
  - The model id is configuration (`GEMINI_MODEL`): `.env` locally, `vars` in `wrangler.jsonc` in production. The key is a Worker secret in production.
  - The provider raises provider-agnostic errors, and one app-level exception handler maps them: timeout → 504, rate limit → 429 with `Retry-After` when the delay is known, any other provider failure → 502. Bodies carry a fixed message, and the cause is only logged.
  - Messages must be 1 to 2000 characters and not blank, to protect the free-tier quota.
- **Alternatives**:
  - `pydantic-settings`: an extra dependency that cannot read the Workers `env` object.
  - Mapping 429 to 503: rejected, because 429 with `Retry-After` tells the client exactly what to do.
  - try/except inside the endpoint: would be repeated in the streaming endpoint.
- **Consequences**: a new provider only implements `generate` and maps its own failures to `LLMTimeoutError`, `LLMRateLimitError` and `LLMUnavailableError`. All three subclass `LLMError`, which the handler catches, and any other `LLMError` subclass falls back to 502. Locally, `uvicorn --env-file` needs `python-dotenv` (a dev dependency), and `pywrangler dev --env-file ../.env` reads the same file.

## 14. Backend layout: layered modules, shared code moves up into `common`

- **Context**: after the walking skeleton, `champbot/` was five flat modules, and two of them mixed responsibilities: `main.py` built the app and mapped exceptions to HTTP responses, and `chat.py` held the route and also created the concrete Gemini provider. Core adds RAG, prompts and streaming, so every issue needs to know where its code goes and which way dependencies point.
- **Decision**:
  - The package is a tree of modules. General modules live under `common/` (`core`, `llm`, later `embeddings` and `vector_store`). Domains (`chat`, later `knowledge`) have one folder per feature (`chat/answer`) and their own `common` for what features share.
  - Every module is split into `presentation`, `application`, `infrastructure` and `domain`. `presentation` may import `application` and `domain`, and `infrastructure` only from `presentation/dependencies.py`. `application` and `infrastructure` may only import `domain`, and they never import each other. Across modules, a layer may also import the same layer of the `common` modules it may depend on, such as `require_setting` from `common/core/infrastructure`. A layer folder exists only once it has content.
  - Siblings never import each other: domains, features, and general modules other than `core`. When two siblings need the same code, it moves up into the `common` beside them.
  - Interfaces live in `domain` and adapters in `infrastructure`. The adapter is chosen in `presentation/dependencies.py` with FastAPI `Depends`, and `main.py` only assembles routers and error handlers.
  - `common/core` holds the base classes other modules inherit from. Each one is added with its first subclass. This change adds `ChampBotError`, the settings lookup and the `error_response` helper.
  - `import-linter` checks the rules in CI: a layers contract per module, forbidden contracts for the upward and sibling rules of `common`, forbidden contracts that keep `fastapi` in `presentation` and `httpx` in `infrastructure`, a forbidden contract that keeps adapter imports in `presentation/dependencies.py`, and a forbidden contract that keeps `domain` and `application` code from importing any `presentation` package.
  - The static frontend will be served by Workers Static Assets, outside the Python package, so serving it costs no Worker CPU time.
- **Alternatives**:
  - Keep the flat package and document the rules: with RAG it would reach about 15 sibling modules, and rules that are only written down drift.
  - Layers directly under `common` (`common/domain`, `common/infrastructure`): unrelated capabilities would share folders, and one settings module would know every provider.
  - Domains calling each other through their application layer: rejected so that each domain can be read and changed alone.
  - Creating every base class upfront (`BaseService`, `BaseEntity`, `ApiModel`): their shape would be guessed, with no subclass to test it against.
  - A dependency injection library: FastAPI `Depends` already wires adapters and lets tests override them, and a new runtime dependency would also have to run on Pyodide.
  - Enforcing the rules only in review: a contract fails CI on the first wrong import.
- **Consequences**:
  - Files sit up to four folders deep (`chat/answer/presentation/rest_api.py`). The depth pays off once `knowledge`, a second chat feature and the RAG modules exist.
  - The layers and adapter-wiring contracts use wildcards (`champbot.*.*`, `champbot.**.presentation`), so new modules and files are checked without editing them. The two `common` contracts name their forbidden targets, because a wildcard would also match the source module, so a new domain or general module is added to them by hand. Sibling independence (domains, features, general modules) is not checked yet, because each level has a single sibling and an `independence` contract over one module checks nothing. The change that adds the second sibling adds that contract. `docs/architecture.md` says so.
  - Every contract also checks indirect imports. The `httpx` and adapter-wiring contracts ignore the imports from `presentation/dependencies.py` into `infrastructure` modules, which removes the only legitimate route from `presentation` to an adapter and to `httpx`.
  - Errors live in `domain`, even when infrastructure raises them (`MissingSettingError`), so that `presentation` can map them without importing `infrastructure`. Each module registers its own error handlers through a `register_*_error_handlers(app)` function next to them.
  - Nested packages work on Workers unchanged: `pywrangler dev` served `/health` and `/chat` from the new layout.

## 15. Pull request previews from the CI workflow

- **Context**: changes, and soon UI changes, should be checked on a real URL before they reach `main`, without touching the production deployment.
- **Decision**:
  - A `preview` job in `.github/workflows/ci.yml` runs `pywrangler versions upload --preview-alias iro-<n>` after the `backend` checks pass, only on pull requests from `iro-<n>-...` branches. A version upload creates a Worker version without deploying it, so production traffic never moves.
  - The alias is `iro-<n>`, taken from the branch name. Full Linear branch names exceed the 63-character DNS label limit of `<alias>-<worker>`.
  - The job checks out the pull request head commit, not GitHub's merge commit, so the preview is the commit shown in the pull request. The same SHA tags the version (`--message`) and appears in the comment.
  - The job keeps a single pull request comment with the URL, found through a hidden marker and edited with `gh` on every push. Only this job gets `pull-requests: write`.
  - A concurrency group per pull request cancels the upload of an older push. The group cancels whichever run is already in it, not the older one, so on its own an older push whose checks finish late could replace a newer preview.
  - Right before uploading, the job checks that its commit is still the pull request head, and skips the upload and the comment if it is not. A push that lands between the check and the upload is still covered, because its own preview cancels the running one or uploads after it. If the newer push fails its `backend` checks, its preview never runs and the older one stays live, which is harmless because the comment still names the commit that was built.
- **Alternatives**:
  - Cloudflare Workers Builds previews: they cannot wait for the CI checks, the pipeline would live outside the repository, and plain `wrangler` does not vendor the Python dependencies (see 10 and 11).
  - A separate frontend Worker or Pages project: it would preview only the UI against the production backend, and add a second deploy target.
  - A Worker per pull request: fully isolated, but each one needs its own secrets and a cleanup job.
  - A marketplace action for the sticky comment: a third-party action with write access to pull requests, for what `gh` does in a few lines.
- **Consequences**:
  - Preview versions inherit the Worker's secrets, so preview `/chat` requests spend the production Gemini quota. Previews are public, like the production URL.
  - `wrangler tail` and Workers Logs do not see requests to preview URLs, so checks that need logs wait until after the merge.
  - Pull requests from forks get no secrets and their preview job fails. The repository has a single contributor, so they are not supported.
  - Cloudflare keeps the latest 1000 aliases, so old previews expire without a cleanup job.

## 16. Multi-turn `/chat` with client-sent history

- **Context**: `/chat` answered each message alone, so a follow-up question lost the earlier turns. The Worker should stay stateless: no KV, D1 or session storage, and no extra bindings, cost or data retention for a demo bot.
- **Decision**:
  - The request body is `{message, history?}`. `history` is a list of `{role: "user" | "assistant", text}` items and defaults to `[]`, so single-turn requests keep working. The server maps `history` and then `message`, in order, to `list[Message]` and passes it to the existing `LLMProvider.generate`. Neither the provider nor the Gemini adapter changes.
  - `history` alternates roles, starting with `user` and ending with `assistant`: item *i* is `user` for even *i* and `assistant` for odd *i*, and its length is even. `message` is always the final user turn, so the model always receives a conversation that ends with the user.
  - User texts (`message` and `user` items) keep the limits of decision 13: 1 to 2000 characters, not blank. Assistant texts must not be blank and are at most 8000 characters. They are not held to 2000, because RAG answers and server-appended flight results can be longer, and a 2000 cap would make the next turn fail.
  - `history` holds at most 20 items and at most 40 000 characters in total across user and assistant texts, to bound the input tokens each request spends from the free-tier quota.
  - Any violation is a 422 before the provider is called. The server never truncates or reorders history. The client trims the oldest user/assistant pairs itself.
  - Validation lives in the `chat/answer` presentation serializers: a discriminated union on `role` for per-item limits, and a `history` field validator for alternation, parity and the total size. No `application` or `domain` layer is added, because the change only maps the request to the existing `Message` value object.
- **Alternatives**:
  - Server-side sessions in KV or D1 keyed by a conversation id: they contradict the stateless Worker and add bindings, expiry and privacy handling.
  - Silently truncating oversized history: the model would see a different conversation than the client believes it sent.
  - Capping assistant texts at 2000 like user texts: it would reject valid follow-ups to long answers.
  - A single global size cap with no per-item assistant limit: one huge assistant item could use the whole budget, and the per-item cap documents the expected answer size.
- **Consequences**:
  - Every turn resends the whole conversation, so input tokens grow with each turn until the client hits the limits. 40 000 characters is roughly 10 000 tokens per request at most.
  - The client controls the history, including assistant turns, and can fabricate them. That is harmless while the user is the only party, but anything the server must trust later (for example flight results it appended) cannot be taken back from `history` without being re-derived or verified on the server.
  - The frontend has to keep the conversation and send it. Until it does, it stays single-turn and still works, because `history` defaults to `[]`. IRO-172 added that: it keeps the conversation and windows it client-side in `frontend/public/history.js`, mirroring these same limits.
  - Changing a limit now touches the constants in both `chat/answer/presentation/serializers.py` and `frontend/public/history.js`, both READMEs, and this entry.

## 17. Prompts as Python modules in `chat/common/domain`

- **Context**: the assistant needs a system prompt, and prompts must live in versioned files, not inline strings. The plan was a Markdown file under `src/`, bundled through a wrangler `rules` entry and read once per isolate by a loader. On `pywrangler dev`, a `.md` file under `src/` could not be read at runtime, neither with `"rules": [{"type": "Data", "globs": ["**/*.md"], "fallthrough": true}]` nor without it.
- **Decision**:
  - Each prompt is a Python module that holds only its text as a module-level string constant. The first one is `ASSISTANT_SYSTEM_PROMPT` in `chat/common/domain/assistant_prompt.py`.
  - Prompts live in `chat/common/domain`: they are chat-domain policy shared by every chat feature, and they hold no I/O, so they are neither `infrastructure` nor part of the provider-agnostic `common/llm`.
  - `chat/answer/presentation/dependencies.py` provides the prompt through `get_system_instruction`, and `POST /chat` passes it to `LLMProvider.generate` as `system_instruction`.
  - A forbidden import-linter contract keeps `champbot.chat.common` from importing `champbot.chat.answer`.
  - The prompt covers tone and scope (flights, baggage, check-in, bookings in general terms, policies and destinations), polite refusal of off-topic requests, never inventing flights, bookings or policies, replying in the user's language, and never claiming to be official Air India.
- **Alternatives**:
  - Markdown or text files bundled with a wrangler `Data` rule and read at runtime: not readable on `pywrangler dev`, as the check above showed.
  - `chat/common/infrastructure/prompts/` with a loader: with no file to read there is nothing to adapt, and the adapter-wiring contract would only let `dependencies.py` import it.
  - `common/llm/domain`: the persona is specific to the chat domain, while `common/llm` is shared plumbing.
  - `chat/answer/domain`: a second chat feature would need the same persona, so it would move to `chat/common` anyway.
  - The route importing the constant directly: one function fewer, but the route would change again once prompt rendering moves into a use case.
- **Consequences**:
  - A prompt is loaded once per isolate by Python's import cache, with no loader and no missing-file failure: a broken prompt module fails at import, in CI.
  - Prompt edits are diffs to a `.py` file that holds only text. The text keeps to ruff's 100-character lines.
  - Templated prompts (RAG context, flight results) will be built from these constants by an `application` service, still without file I/O.
  - The prompt's effect is not unit tested. It is checked with scripted prompts on `pywrangler dev`, kept in the pull request as the seed of the evaluation suite.
  - Each new chat feature is added by hand to the forbidden targets of the `chat/common` contract.

## 18. Policy corpus in `backend/data/`, chunked by a pure `knowledge/ingest` domain, run by a CLI

- **Context**: RAG (decision 14's parent issue, IRO-174) needs Air India policy text, chunked within bge-m3 and Vectorize's limits, and ingested outside the request path. airindia.com is JS-rendered, so a plain HTTP fetch times out.
- **Decision**:
  - The corpus is 7 Markdown files in `backend/data/policies/`, with front matter `title`, `source_url` and `retrieved_at`, copied by hand from browser-rendered pages — no scraper. Checked and cabin baggage share one file; an inline `<!-- source_url: ... -->` comment right after a heading overrides the file's front-matter `source_url` for that heading's sections, so the cabin-baggage chunks still cite the cabin page.
  - `backend/data/` sits outside `src/` for the same reason decision 17 found non-`.py` files under `src/` unreadable on Workers, and because the corpus is never needed at runtime — only its vectors are, once IRO-180 ingests them.
  - The eval seed lives alongside it, at `backend/data/eval/policy_questions.json`.
  - The chunker is pure domain logic in a new `knowledge` domain (`knowledge/ingest/domain`): it splits the body at every heading, packs consecutive sections up to 500 estimated tokens (`characters / 4`, no tokenizer dependency), and falls back to paragraph, then line, then hard-character splitting for a single oversized section. Ids are `<slug>-<n>`; metadata is `{title, source_url, section, text}`; the embedded text is `"title > section"` followed by the chunk text. It checks every id and metadata blob against Vectorize's limits (64 bytes, 10 KiB) before returning, so a bad corpus fails at `--dry-run` time, not during the IRO-180 upsert.
  - The CLI (`knowledge/ingest/presentation/cli.py`, script name `champbot-ingest`) has no adapters yet. When IRO-180 adds the Workers AI and Vectorize calls, they are wired through a new `knowledge/ingest/presentation/dependencies.py`, the one path the adapter-wiring contract already lets through.
  - A `champbot.chat` / `champbot.knowledge` `independence` contract is added, and `champbot.knowledge` joins the forbidden targets of "Common does not depend on domains".
- **Alternatives**:
  - A real tokenizer (tiktoken, or bge-m3's own) instead of `characters / 4`: a heavy dependency the issue explicitly wanted to avoid, for a soft 300-500 token target where chars/4 only slightly over-counts English text.
  - Chunking by paragraph or a fixed-size sliding window: loses the heading context that `section` and the `"title > section"` embed prefix depend on.
  - One chunk per heading, with no packing: the FAQ-style pages have 50-150-token Q&As, so this would give many tiny, weak chunks well under the 300-500 target.
  - A CLI in `backend/scripts/`, outside the `champbot` package: import-linter only checks `champbot`, so a script there could import infrastructure freely and quietly escape the adapter-wiring contract.
  - YAML or CSV for the eval seed: YAML needs a dependency with no stdlib parser, and CSV cannot hold both the questions and the off-topic queries cleanly.
- **Consequences**:
  - Token counts are approximate: `characters / 4` over-counts English text a little, so chunks err small rather than large.
  - Refreshing the corpus is a manual, dated copy; `retrieved_at` shows how stale it is, and there is no scraper to re-run.
  - `DocumentChunk` stays inside `knowledge/ingest`. Anything `chat` needs at query time moves to `common/vector_store/domain` in IRO-180 or IRO-181, as the independence contract requires.
  - The CLI ships inside the Worker bundle like every other module, but nothing imports it, so it has no runtime cost or effect.
