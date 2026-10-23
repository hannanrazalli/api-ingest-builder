# API Ingest Builder progress

## Authorization and constraints
User authorized Phases 2–7 autonomously, in order, overriding inter-phase pauses in AGENTS.md. Single agent; no delegation. Never read .env or auth.json. No real LLM/Codex calls; offline HTTP/LLM fixtures and fake CLI only. Windows/PowerShell. After each phase: full tests/lint, isolated no-key Compose build/up/health/UI/down, security scan, completeness audit, commit and push. Fix gate failures up to three attempts, record blockers and continue independent work.

## Baseline
Phases 1/1b complete; last commit 6a8dc55. 75 tests passing, one upstream TestClient deprecation warning. Docker API/Demo and host-only Codex mode. No research/generation/product UI/conversion/Office yet.

## Phase status
- Phase 2: COMPLETE — typed event-emitting Prober/OpenAPI+Swagger JSON/YAML/local refs, robots-aware Fetcher with bounded optional offline JS hydration, BM25 Retriever, structured provenance-checked Extractor, host-bound GET Verifier, Profiler, FAST/SMART Repair, deterministic async Orchestrator, cache-first SQLite index/results, research/history APIs and try-url.ps1. Six actual offline event recordings: cache miss/hit, OpenAPI, repair, docs-not-found, budget block. Gate: 88 passed (1 upstream warning), Ruff/TypeScript clean, isolated Compose healthy/health/UI/Demo/key masking/down/security PASS. Calls: 0 OpenAPI/cache/Demo; 1 normal; 3 two-repair scenario; 0 blocked. No Phase 2 stubs; optional JS supports offline hydration only (live XHR needs static/OpenAPI URL), real provider/API runs intentionally untested.
- Phase 3: pending — Jinja2 generation/goldens.
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
Phase 3: implement six Jinja2 generation modes with env-only secrets, retries/rate limits/date windows/pagination/NDJSON/S3, golden fixture outputs and syntax/lint/idempotency tests. Then gate/commit and continue Phase 4 automatically.
