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
- **Consequences**: Python Workers run on Pyodide (CPython compiled to WebAssembly), so every dependency must be pure Python or available for Pyodide, and the free plan's CPU limit per request applies. The Python version is pinned to 3.12; it must be revalidated against the Pyodide version the Workers runtime ships when the deployment is set up (IRO-159).

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
- **Alternatives**: a frontend framework, rejected because a single chat screen does not justify a build step and a second toolchain.
- **Consequences**: one deployable unit. SSE is one-directional (server to client), which is all a chat answer stream needs.

## 8. Tooling: uv, ruff, pyright, pytest

- **Context**: the project needs dependency management, linting, formatting, type checking and tests, all enforced in CI.
- **Decision**: uv for Python and dependency management, ruff for lint and format, pyright in strict mode for types, pytest for tests.
- **Alternatives**: mypy instead of pyright, rejected because pyright is faster and its strict mode catches more than mypy's defaults.
- **Consequences**: `uv.lock` is committed and CI installs with `uv sync --locked`, so CI fails if the lockfile is out of date.

## 9. Monorepo with `backend/` and `frontend/`

- **Context**: the repository holds the Python backend and the static frontend.
- **Decision**: one repository with two top-level folders. `backend/` is a self-contained uv project; `frontend/` holds the static files.
- **Alternatives**:
  - A single uv project at the root: mixes Python tooling with the frontend.
  - A uv workspace with `backend` as a member: only useful with several Python packages.
- **Consequences**: backend commands run from `backend/`, and CI sets that as its working directory.
