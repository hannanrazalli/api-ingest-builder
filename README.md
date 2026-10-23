# API Ingest Builder

Portable data engineering tools with deterministic processing, SQLite caching, and budgeted LLM use.

**Phase 1 is implemented.** This release provides onboarding, provider/settings APIs, typed spec/job/event contracts, caches, Cost Guard, protected fetch infrastructure and persistent SSE. Research, recorded API demos, generation, conversion, explanations and the Office visualization arrive in Phases 2–6. The foundation makes no LLM calls on startup or when changing settings.

## Quickstart (PowerShell or a POSIX shell)

```powershell
git clone https://github.com/hannanrazalli/api-ingest-builder.git
cd api-ingest-builder
docker compose up --build
```

Open [localhost:8000](http://localhost:8000). No `.env` is needed. Select Demo mode or enter provider settings locally. FastAPI serves the Next.js static export in one container; only SQLite data persists in the `app-data` volume. Stop with `docker compose down`; the volume remains.

Choose Anthropic, OpenAI, or an OpenAI-compatible base URL (include `/v1` where appropriate). Enter model names from the vendor's current documentation; none are hardcoded. Local compatible servers can use a non-secret placeholder key if they do not require authentication. Provider endpoints are trusted administrator configuration and can intentionally address local model servers. Research URLs must use the separate SSRF-protected fetcher.

Optional nonempty environment overrides take precedence over stored UI settings: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `MODEL_FAST`, `MODEL_SMART`. `.env.example` documents these variables. Compose can use a user-maintained local `.env`; do not commit it or share its contents. The agent and development scripts must never read or print that file. Settings responses contain only a fixed key mask. Actual credentials are stored locally in SQLite so requests can authenticate; protect the local data directory/volume. This is a local single-user app, bound to loopback by default.

## Development on Windows

Install Python 3.12, uv, Node.js 22 and pnpm. From PowerShell:

```powershell
.\scripts\dev.ps1
.\scripts\test.ps1
.\scripts\lint.ps1
.\scripts\build.ps1
```

`dev.ps1` installs dependencies, exports the frontend, then runs the backend with reload on [localhost:8000](http://localhost:8000). Rerun after frontend changes to regenerate the export. No Node process runs in production. The scripts stop on failed commands and return to the starting directory.

Equivalent Make targets for POSIX environments:

```sh
make dev
make test
make lint
make build
```

Python dependencies are locked in `uv.lock`; frontend dependencies in `frontend/pnpm-lock.yaml`. Test/lint scripts check the backend and TypeScript. Build commands explicitly use the non-secret `.env.example`; only user-invoked runtime Compose commands load local overrides. `uv run --no-env-file` prevents accidental dotenv loading. The reference file is preserved verbatim and excluded from application linting; its default URL is a Markdown link from the supplied text, so future generation must use validated spec URLs instead.

## Optional JavaScript documentation support

Only the explicit JS profile overlay installs Playwright and Chromium, into the same app container:

```powershell
docker compose -f docker-compose.yml -f docker-compose.js.yml --profile js up --build
```

The normal image has neither. The overlay configuration is validated in Phase 1; the optional browser image will receive integration coverage with the Phase 2 fetcher. The fetcher pipeline and its graceful missing-Playwright message are Phase 2 work.

## Foundation APIs

- `GET /api/health`: status and current phase.
- `GET /api/settings`: effective settings, key mask, Demo state, override field names.
- `PUT /api/settings`: partial local update; omit the key to retain it, send an empty key to clear it.
- `POST /api/onboarding/demo`: select Demo mode, retaining any stored key while disabling live calls. Saving provider settings leaves explicit Demo mode.
- `POST /api/jobs`: create a foundation job with its initial dispatcher event.
- `GET /api/jobs/{id}`: persisted status and usage.
- `GET /api/jobs/{id}/events`: SSE with durable sequence IDs; reconnect with `Last-Event-ID` or `?after=`. Terminal jobs send `done` after replay.

The frontend event type is generated from the Pydantic contract using `uv run --no-env-file python scripts/export_event_type.py`; its parity is tested. Agent events include only short metadata, never document bodies. All event publishers must use `EventBus` with the current job's secrets for redaction.

Cache namespaces are `spec_cache`, `convert_cache`, `explain_cache`, `sample_cache`; job/events/settings are also persisted in SQLite with parameterized queries and WAL. Structured LLM responses have their own prefixed content keys including provider, model, endpoint, prompt, schema and input. Unchanged input can return a validated cached result with zero calls.

Cost Guard reserves a conservative UTF-8 byte token bound plus overhead before network I/O, reserves the full requested output, then reconciles reported usage. Default per-job limits: 3 calls, 20,000 input tokens and 4,000 output tokens. Failures retain reservations. Calls are never automatically retried; routing and model escalation belong to the later deterministic pipeline. A blocked call persists a waiting job/event; user override UI is Phase 7. Prices default to zero (unconfigured), not a claim that a paid provider is free; configure `input_usd_per_million`, `cached_usd_per_million` and `output_usd_per_million` through the settings API for estimates. Provider pricing/cache-write premiums vary; cost is an estimate. Cached token counts come from provider usage. Anthropic uses cached static system/tool blocks; OpenAI uses a stable prefix for automatic caching. Cache support depends on the configured provider/model.

`SafeFetcher` only issues GET requests, resolves and validates every redirect, rejects any mixed private/public DNS answer, pins the actual connection to the validated address while retaining TLS SNI/Host, limits total time, redirects and response bytes, and rejects compressed bodies to avoid decompression bombs. Explicit credential headers require a matching spec hostname and cannot cross hosts. Provider requests disable redirects to prevent key forwarding. No fetched instructions are executed: retrieved inputs enter LLM requests as JSON data beneath a fixed untrusted-data system policy.

## Verification

Run `python scripts/smoke_docker.py` after the Docker build for a disposable production-container check: HTTP/static export, onboarding, secret masking, explicit Demo mode, SSE replay, SQLite persistence across restart, non-root execution and absence of Node/Playwright. It uses a dummy key and removes only its own temporary container and anonymous volume. It does not load dotenv.

## Phase plan

1. Foundation (current).
2. Research pipeline and recorded fixtures.
3. Deterministic Jinja2 code generation.
4. Builder UI and live timeline.
5. Converter and Explain.
6. Event-driven Office.
7. Polish, accessibility and clean-machine verification.

Development stops after each phase pending `continue`. No Office code or third-party sprites have been copied.
