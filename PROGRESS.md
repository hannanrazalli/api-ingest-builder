# API Ingest Builder progress

## Authorization and constraints
User authorized Phases 2–7 autonomously, in order, overriding inter-phase pauses in AGENTS.md. Single agent; no delegation. Never read .env or auth.json. No real LLM/Codex calls; offline HTTP/LLM fixtures and fake CLI only. Windows/PowerShell. After each phase: full tests/lint, isolated no-key Compose build/up/health/UI/down, security scan, completeness audit, commit and push. Fix gate failures up to three attempts, record blockers and continue independent work.

## Baseline
Phases 1/1b complete; last commit 6a8dc55. 75 tests passing, one upstream TestClient deprecation warning. Docker API/Demo and host-only Codex mode. No research/generation/product UI/conversion/Office yet.

## Phase status
- Phase 2: COMPLETE — typed event-emitting Prober/OpenAPI+Swagger JSON/YAML/local refs, robots-aware Fetcher with bounded optional offline JS hydration, BM25 Retriever, structured provenance-checked Extractor, host-bound GET Verifier, Profiler, FAST/SMART Repair, deterministic async Orchestrator, cache-first SQLite index/results, research/history APIs and try-url.ps1. Six actual offline event recordings: cache miss/hit, OpenAPI, repair, docs-not-found, budget block. Gate: 88 passed (1 upstream warning), Ruff/TypeScript clean, isolated Compose healthy/health/UI/Demo/key masking/down/security PASS. Calls: 0 OpenAPI/cache/Demo; 1 normal; 3 two-repair scenario; 0 blocked. No Phase 2 stubs; optional JS supports offline hydration only (live XHR needs static/OpenAPI URL), real provider/API runs intentionally untested.
- Phase 3: COMPLETE — six Jinja2 modes, validated spec/user fields, env-only credentials, deterministic formatting, inclusive UTC ISO/unix dates, retry/Retry-After/rate limits, bounded page/offset/cursor/link pagination, documented date windows, profile-backed NDJSON, atomic local partition replacement, Airflow/S3Hook replace=True and skip-existing. API /api/generate and event-log implemented. Twelve golden outputs, mocked HTTP/S3 runtime checks, compile/lint/idempotency coverage. Gate: 106 passed (1 upstream warning); lint/TypeScript/Compose/security PASS. Generator LLM calls: 0 for every mode/toggle. No stubs. Explicit cursor response path is required rather than guessed; custom header/body GET params are rejected safely.
- Phase 4: pending — thin Builder, full shell, screenshots.
- Phase 5: pending — converters/Explain, 30+ SQL cases.
- Phase 6: pending — event-driven Office and replay tests.
- Phase 7: pending — override flow, accessibility, clean checkout and documentation.

## LLM targets
OpenAPI/cache/Demo: 0; normal research <=1; conditional repair <=3; generation/UI/Office: 0. Cost Guard enforced for API and Codex.

## Known issues / deferred
Real provider/API behavior is intentionally not exercised. Optional JS-doc fetching must remain SSRF-safe. UI/generator/converter/Office are future phase work, not completed stubs.

## Blocked
None.

## Next step
Phase 4a: thin Demo Builder via existing research/SSE/generate APIs. Phase 4b: full responsive shell, history, badges, meters, onboarding, themes, command palette; local Monaco assets, Framer Motion, accessible UI primitives. Add Playwright dev-only, review desktop/tablet screenshots, then phase gate/commit. Continue Phase 5 automatically.
