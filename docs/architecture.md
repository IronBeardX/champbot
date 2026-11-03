# Backend architecture

Where code goes in `backend/src/champbot/` and which way dependencies point. Decision 14 in [`decisions.md`](decisions.md) records why.

## The rule

The package is a tree of modules, and every module is split into the same four layers.

**Siblings never import each other.** When two siblings need the same code, it moves up into the `common` beside them.

| Level | Siblings | Their shared code |
|---|---|---|
| Top | Domains: `chat`, later `knowledge` | `common/`, made of general modules |
| Inside `common` | General modules: `llm`, later `embeddings`, `vector_store` | `common/core` |
| Inside a domain | Features: `chat/answer`, later `chat/stream` | `<domain>/common` |

So a domain never uses another domain, a feature never uses another feature, and a general module only uses `common/core`. `common` never imports a domain, and `common/core` imports no other module.

## Layers

Each module has up to four layers. A layer folder exists only once it has content.

| Layer | Holds | May import |
|---|---|---|
| `presentation` | Routes (`rest_api.py`), request and response models (`serializers.py`), FastAPI dependencies that pick concrete adapters (`dependencies.py`), error-to-status mapping and its registration (`errors.py`) | `application` and `domain`. `infrastructure` only from `dependencies.py` |
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
│   │   │   └── settings.py        # Workers env or os.environ lookup, require_setting
│   │   └── presentation/
│   │       ├── errors.py          # error_response helper, MissingSettingError → 500, register_core_error_handlers
│   │       └── rest_api.py        # GET /health
│   └── llm/
│       ├── domain/
│       │   └── provider.py        # LLMProvider interface and the LLMError hierarchy
│       ├── infrastructure/
│       │   ├── gemini.py          # GeminiProvider over the Gemini REST API
│       │   └── settings.py        # GeminiSettings, load_gemini_settings
│       └── presentation/
│           └── errors.py          # LLMError → 504, 429 or 502, register_llm_error_handlers
└── chat/
    └── answer/                    # feature: single-turn POST /chat
        └── presentation/
            ├── dependencies.py    # get_llm_provider: builds the Gemini adapter from settings
            ├── rest_api.py        # POST /chat
            └── serializers.py     # ChatRequest, ChatResponse
```

## Base classes

`common/core` holds the classes and helpers that other modules build on. Each one is added by the first change that has a class to inherit from it, so no base sits unused.

| Base or helper | Location | Status |
|---|---|---|
| `ChampBotError` | `common/core/domain/exceptions.py` | In use: `LLMError`, `MissingSettingError` |
| `error_response()` | `common/core/presentation/errors.py` | In use: every error handler |
| `settings_lookup()`, `require_setting()` | `common/core/infrastructure/settings.py` | In use: `load_gemini_settings` |
| `BaseService` | `common/core/application/services.py` | Added with the first use case that orchestrates several steps |
| `BaseEntity` | `common/core/domain/models.py` | Added with the first domain model |
| `ApiModel` | `common/core/presentation/serializers.py` | Added when two serializers share configuration |

## Where future pieces go

| Piece | Location |
|---|---|
| Chat orchestration (retrieve, render the prompt, generate) | `chat/answer/application/services.py` |
| RAG retrieval | `chat/answer/application/`, or `chat/common` once a second chat feature needs it. It uses the `common/embeddings` and `common/vector_store` interfaces |
| Streaming answers | A `chat/stream` feature. What it shares with `answer` moves to `chat/common` |
| Prompts (versioned files) | `chat/common/infrastructure/prompts/`, with a loader next to them. Wrangler only bundles `.py` files by default, so the first prompt change also makes the Worker bundle these files |
| Embeddings | `common/embeddings`: `Embedder` in `domain`, the Workers AI adapter in `infrastructure` |
| Vector database | `common/vector_store`: `VectorStore` and `Chunk` in `domain`, the Vectorize adapter in `infrastructure` |
| Document ingestion | `knowledge/ingest/`, the first feature of a `knowledge` domain, run by a script outside the request path |
| Conversation state | Decided by its own Core issue. Its models belong to the `chat` domain |
| Static frontend | Workers Static Assets, configured in `wrangler.jsonc`. Not part of the Python package |

## Enforcement

`uv run lint-imports` checks these rules with [import-linter](https://import-linter.readthedocs.io/), and CI runs it next to the tests. The contracts live in `backend/pyproject.toml`:

- **Every module is layered**: the layer order inside every module two levels below `champbot` (`champbot.*.*`: `common/core`, `common/llm`, `chat/answer`, and any new one).
- **Common does not depend on domains** and **Core does not depend on other common modules**: the upward and sibling rules for `common`. Their forbidden targets are named one by one (`champbot.chat`, `champbot.common.llm`), because a wildcard would also match the source module itself.
- **FastAPI stays in presentation** and **httpx stays in infrastructure**: where third-party packages may be imported. Both check indirect imports too. The `httpx` contract lets `presentation/dependencies.py` reach `httpx` through the adapters it wires, with the same `ignore_imports` as the adapter-wiring contract below.
- **Only presentation dependencies pick adapters**: outside `presentation/dependencies.py`, no `domain`, `application` or `presentation` code imports an `infrastructure` module, directly or indirectly, in its own module or in another one. `main.py` and `infrastructure` code are exempt, so an adapter may build on `common/core/infrastructure`. The contract covers every presentation file and lets only `dependencies.py` through with `ignore_imports`. That pattern matches modules inside an `infrastructure` package, so `dependencies.py` imports from a module such as `infrastructure.gemini`, never from the `infrastructure` package itself.
- **Domain and application never reach presentation**: no `domain` or `application` code imports any `presentation` package, in its own module or in another one. Together with the adapter-wiring contract, this closes the indirect route from a use case to an adapter through another module's `dependencies.py`, which the layers contract cannot see because it works inside one module.

The layers, third-party and adapter-wiring contracts use wildcards, so new modules and files are covered without editing them. The two `common` contracts are not: a new domain is added to the forbidden targets of **Common does not depend on domains**, and a new general module to those of **Core does not depend on other common modules**. Sibling independence has nothing to check while each level has a single sibling (one domain, one feature, one general module besides `core`). The change that adds the second one adds an `independence` contract for that level, for example `["champbot.chat", "champbot.knowledge"]`. Likewise, the change that creates the first `<domain>/common` adds a forbidden contract that keeps it from importing that domain's features.
