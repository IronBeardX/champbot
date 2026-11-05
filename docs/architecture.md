# Backend architecture

Where code goes in `backend/src/champbot/` and which way dependencies point. Decision 14 in [`decisions.md`](decisions.md) records why.

## The rule

The package is a tree of modules, and every module is split into the same four layers.

**Siblings never import each other.** When two siblings need the same code, it moves up into the `common` beside them.

| Level | Siblings | Their shared code |
|---|---|---|
| Top | Domains: `chat`, `knowledge` | `common/`, made of general modules |
| Inside `common` | General modules: `llm`, `flights`, `embeddings`, `vector_store` | `common/core` |
| Inside a domain | Features: `chat/answer`, later `chat/stream` | `<domain>/common` |

So a domain never uses another domain, a feature never uses another feature, and a general module only uses `common/core`. `common` never imports a domain, and `common/core` imports no other module.

## Layers

Each module has up to four layers. A layer folder exists only once it has content.

| Layer | Holds | May import |
|---|---|---|
| `presentation` | Routes (`rest_api.py`), request and response models (`serializers.py`), FastAPI dependencies that pick concrete adapters (`dependencies.py`), error-to-status mapping and its registration (`errors.py`), CLI entry points (`cli.py`) run outside the request path | `application` and `domain`. `infrastructure` only from `dependencies.py` |
| `application` | Use cases (`services.py`) that orchestrate domain objects through their interfaces | `domain` |
| `infrastructure` | Adapters that implement domain interfaces against external services, and settings loading | `domain` |
| `domain` | Interfaces (`Protocol`s), models and errors | no other layer, and no third-party I/O library (`httpx`, `fastapi`, cloud clients) |

The column lists the layers of the same module. Across modules, a layer may also import the same layer of the `common` modules it is allowed to depend on: `common/llm/infrastructure/settings.py` builds on `require_setting` from `common/core/infrastructure`, `common/llm/presentation/errors.py` uses `error_response` from `common/core/presentation`, and `LLMError` in `common/llm/domain` subclasses `ChampBotError` from `common/core/domain`. A future feature service will subclass `BaseService` from `common/core/application` the same way.

`application` and `infrastructure` never import each other. A use case depends on an interface, and the presentation layer picks the adapter that implements it. `fastapi` is imported only in `presentation` and `main.py`, and `httpx` only in `infrastructure`.

`main.py` is the composition root: it builds the app, includes the routers and calls each module's `register_*_error_handlers`. `worker.py` is the Workers entrypoint and only wraps `main.app`.

## Modules

```text
champbot/
├── main.py                        # create_app: routers and error handlers
├── common/
│   ├── core/
│   │   ├── domain/
│   │   │   └── exceptions.py      # ChampBotError (base of every error the app raises), MissingSettingError
│   │   ├── infrastructure/
│   │   │   ├── settings.py        # Workers env or os.environ lookup, require_setting
│   │   │   ├── cloudflare.py      # CloudflareSettings, load_cloudflare_settings, CLOUDFLARE_API_BASE, describe_cloudflare_errors
│   │   │   └── http_client.py     # open_http_client: the one place presentation code reaches an httpx.AsyncClient
│   │   └── presentation/
│   │       ├── errors.py          # error_response helper, MissingSettingError → 500, register_core_error_handlers
│   │       └── rest_api.py        # GET /health
│   ├── llm/
│   │   ├── domain/
│   │   │   ├── message.py         # Role and Message value objects of a conversation
│   │   │   └── provider.py        # LLMProvider interface and the LLMError hierarchy
│   │   ├── infrastructure/
│   │   │   ├── gemini.py          # GeminiProvider over the Gemini REST API
│   │   │   └── settings.py        # GeminiSettings, load_gemini_settings
│   │   └── presentation/
│   │       └── errors.py          # LLMError → 504, 429 or 502, register_llm_error_handlers
│   ├── flights/
│   │   ├── domain/
│   │   │   ├── flight.py          # Cabin and Flight value objects
│   │   │   └── search.py          # FlightSearch interface
│   │   ├── infrastructure/
│   │   │   └── schedule_template.py  # Weekly Air India template, generates flights for any date with deterministic fares
│   │   └── presentation/
│   │       ├── dependencies.py    # get_flight_search builds the schedule-template adapter
│   │       ├── rest_api.py        # GET /flights
│   │       └── serializers.py     # FlightSearchQuery, FlightResponse
│   ├── embeddings/
│   │   ├── domain/
│   │   │   └── embedder.py        # Embedder interface, EmbeddingError and EmbeddingTimeoutError
│   │   ├── infrastructure/
│   │   │   └── workers_ai.py      # WorkersAIEmbedder over the Workers AI REST API (@cf/baai/bge-m3)
│   │   └── presentation/
│   │       └── errors.py          # EmbeddingError → 504 or 502, register_embedding_error_handlers
│   └── vector_store/
│       ├── domain/
│       │   └── store.py           # Chunk, ScoredChunk, VectorStore interface (upsert and query), VectorStoreError and VectorStoreTimeoutError
│       ├── infrastructure/
│       │   └── vectorize.py       # VectorizeStore over the Vectorize v2 REST API
│       └── presentation/
│           └── errors.py          # VectorStoreError → 504 or 502, register_vector_store_error_handlers
├── chat/
│   ├── common/
│   │   └── domain/
│   │       ├── assistant_prompt.py  # ASSISTANT_SYSTEM_PROMPT: Air India assistant persona
│   │       └── rag_prompt.py      # RAG_PROMPT, RAG_CHUNK, NO_POLICY_CONTEXT: text-only RAG templates
│   └── answer/                    # feature: POST /chat, multi-turn with client-sent history, RAG-grounded
│       ├── application/
│       │   ├── retrieval.py       # retrieve_policy_chunks: embed, query Vectorize, filter by score (also used by the IRO-189 eval)
│       │   └── services.py        # answer_chat: builds the retrieval query, renders the rag prompt, calls the LLM, builds sources
│       ├── infrastructure/
│       │   └── settings.py        # RetrievalSettings, load_retrieval_settings
│       └── presentation/
│           ├── dependencies.py    # get_llm_provider, get_retrieval_ports (TEMP(IRO-164)), get_min_score
│           ├── rest_api.py        # POST /chat, delegates to answer_chat
│           └── serializers.py     # ChatRequest (message + history), ChatResponse (answer + sources), SourceResponse
└── knowledge/
    └── ingest/                    # feature: policy corpus chunking and ingestion, run by the champbot-ingest CLI
        ├── domain/
        │   ├── document.py        # PolicyDocument, parse_policy_document, InvalidPolicyDocumentError
        │   └── chunker.py         # estimate_tokens, DocumentChunk, chunk_document
        ├── application/
        │   └── ingest.py          # IngestReport, ingest_chunks: embeds every chunk, then upserts
        └── presentation/
            ├── dependencies.py    # open_ingest_ports: builds the Workers AI and Vectorize adapters
            └── cli.py             # champbot-ingest --dry-run, or embed + upsert
```

The policy corpus itself lives in `backend/data/policies/` and the eval seed in `backend/data/eval/`, both outside `src/` (decision 17: non-`.py` files under `src/` aren't readable on Workers at runtime, and this data is only ever needed locally, never by the deployed Worker).

## Base classes

`common/core` holds the classes and helpers that other modules build on. Each one is added by the first change that has a class to inherit from it, so no base sits unused.

| Base or helper | Location | Status |
|---|---|---|
| `ChampBotError` | `common/core/domain/exceptions.py` | In use: `LLMError`, `MissingSettingError`, `InvalidSettingError`, `InvalidPolicyDocumentError`, `EmbeddingError`, `VectorStoreError` |
| `error_response()` | `common/core/presentation/errors.py` | In use: every error handler |
| `settings_lookup()`, `require_setting()` | `common/core/infrastructure/settings.py` | In use: `load_gemini_settings`, `load_cloudflare_settings` |
| `BaseService` | `common/core/application/services.py` | Added with the first use case that orchestrates several steps |
| `BaseEntity` | `common/core/domain/models.py` | Added with the first domain model |
| `ApiModel` | `common/core/presentation/serializers.py` | Added when two serializers share configuration |

## Where future pieces go

| Piece | Location |
|---|---|
| Streaming answers | A `chat/stream` feature. What it shares with `answer` moves to `chat/common` |
| Prompts (versioned files) | `chat/common/domain/`, one module per prompt that holds only its text as a constant. Python Workers do not make non-`.py` files under `src/` readable at runtime (decision 17) |
| Document ingestion | `knowledge/ingest/`: the chunker, the `champbot-ingest --dry-run` CLI (IRO-178), and its write path (IRO-180) embedding every chunk through `Embedder` and upserting through `VectorStore`, wired from `knowledge/ingest/presentation/dependencies.py` |
| Flight search in `/chat` | `chat/answer/presentation/dependencies.py` wires the `FlightSearch` interface from `common/flights/domain`, same as `get_llm_provider`. A real flight API is a new `common/flights/infrastructure` adapter; callers and the interface stay unchanged |
| Static frontend | Workers Static Assets, configured in `wrangler.jsonc`. Not part of the Python package |

## Enforcement

`uv run lint-imports` checks these rules with [import-linter](https://import-linter.readthedocs.io/), and CI runs it next to the tests. The contracts live in `backend/pyproject.toml`:

- **Every module is layered**: the layer order inside every module two levels below `champbot` (`champbot.*.*`: `common/core`, `common/llm`, `common/flights`, `chat/common`, `chat/answer`, and any new one).
- **Common does not depend on domains** and **Core does not depend on other common modules**: the upward and sibling rules for `common`. Their forbidden targets are named one by one (`champbot.chat`, `champbot.knowledge`, `champbot.common.llm`, `champbot.common.flights`, `champbot.common.embeddings`, `champbot.common.vector_store`), because a wildcard would also match the source module itself.
- **Domains are independent**: `champbot.chat` and `champbot.knowledge` never import each other, in either direction. It is the sibling-independence contract for the domain level, added now that there are two domains (see the last paragraph below).
- **General modules are independent**: `common/llm`, `common/flights`, `common/embeddings` and `common/vector_store` never import each other, in any direction. It is the same kind of contract, for the general-module level, added now that `common` has siblings besides `core`.
- **Chat common does not depend on chat features**: `chat/common` never imports a `chat` feature, so shared chat code only flows down into features. Its forbidden targets are named one by one (`champbot.chat.answer`) for the same reason.
- **FastAPI stays in presentation** and **httpx stays in infrastructure**: where third-party packages may be imported. Both check indirect imports too. The `httpx` contract lets `presentation/dependencies.py` reach `httpx` through the adapters it wires, with the same `ignore_imports` as the adapter-wiring contract below.
- **Only presentation dependencies pick adapters**: outside `presentation/dependencies.py`, no `domain`, `application` or `presentation` code imports an `infrastructure` module, directly or indirectly, in its own module or in another one. `main.py` and `infrastructure` code are exempt, so an adapter may build on `common/core/infrastructure`. The contract covers every presentation file and lets only `dependencies.py` through with `ignore_imports`. That pattern matches modules inside an `infrastructure` package, so `dependencies.py` imports from a module such as `infrastructure.gemini`, never from the `infrastructure` package itself.
- **Domain and application never reach presentation**: no `domain` or `application` code imports any `presentation` package, in its own module or in another one. Together with the adapter-wiring contract, this closes the indirect route from a use case to an adapter through another module's `dependencies.py`, which the layers contract cannot see because it works inside one module.

The layers, third-party and adapter-wiring contracts use wildcards, so new modules and files are covered without editing them. The `common` contracts are not: a new domain is added to the forbidden targets of **Common does not depend on domains**, a new general module to those of **Core does not depend on other common modules** and to the general-module `independence` contract's module list, and a new chat feature to those of **Chat common does not depend on chat features**. Sibling independence has nothing to check while a level has a single sibling: the domain level had only `chat` until `knowledge` arrived, and the general-module level had only `llm` until `flights` arrived, which is why **Domains are independent** and **General modules are independent** are only added now, each as an `independence` contract listing every sibling at that level (`["champbot.chat", "champbot.knowledge"]`, `["champbot.common.llm", "champbot.common.flights", "champbot.common.embeddings", "champbot.common.vector_store"]`). The feature level (inside a domain) still waits for its own second sibling. Likewise, the change that creates another domain's `<domain>/common` adds a forbidden contract like the `chat/common` one, which keeps it from importing that domain's features.
