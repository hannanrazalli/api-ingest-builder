import asyncio
import hashlib
from urllib.parse import urlsplit
from uuid import uuid4

from backend.agents.base import AgentContext
from backend.agents.extractor import Extractor
from backend.agents.fetcher import DocClient, Fetcher
from backend.agents.prober import Prober, normalize_url
from backend.agents.profiler import Profiler
from backend.agents.repair import Repair
from backend.agents.retriever import Retriever
from backend.agents.verifier import VerificationFailed, Verifier
from backend.cache.store import cache_key
from backend.cost_guard import BudgetExceeded, CostGuard
from backend.fixtures.runtime import FixtureHTTP, load_fixture
from backend.llm.errors import ProviderError
from backend.llm.provider import Provider
from backend.models import Job, Spec
from backend.models.research import Chunk, ResearchResult
from backend.orchestrator.events import EventBus
from backend.security.redaction import register_secrets
from backend.security.ssrf import SafeFetcher
from backend.settings import effective_settings, public_settings


class ResearchPipeline:
    def __init__(self, store, *, fetcher=None, provider_factory=None):
        self.store, self.fetcher, self.provider_factory = store, fetcher, provider_factory

    async def run(self, request, job=None):
        settings = effective_settings(self.store)
        job = job or Job(id=str(uuid4()))
        job.status = "running"
        self.store.save_job(job)
        self.store.save_pending(job.id, "research", request)
        key = request.api_key.get_secret_value() if request.api_key else None
        register_secrets(settings.api_key.get_secret_value(), key)
        bus = EventBus(self.store, [settings.api_key.get_secret_value(), key])
        ctx = AgentContext(self.store, job, bus)
        warnings, spec, profile, hit = [], None, None, False
        demo = public_settings(settings)["demo_mode"] if request.demo is None else request.demo
        status = "error"
        try:
            async with asyncio.timeout(180):
                async with ctx.step("orchestrator", "Research API documentation") as progress:
                    url = normalize_url(request.url)
                    domain = urlsplit(url).hostname
                    index_key = ("demo:" if demo else "live:") + url
                    cached_key = None if request.force else self.store.index(index_key)
                    cached = self.store.get("spec_cache", cached_key) if cached_key else None
                    guard = CostGuard(settings, job)
                    provider = (
                        self.provider_factory(settings, self.store, guard, bus)
                        if self.provider_factory
                        else Provider(settings, self.store, guard, bus)
                    )
                    demo_spec, demo_sample = None, None
                    fetcher = self.fetcher or SafeFetcher()
                    if demo:
                        fixture = (
                            "coingecko"
                            if domain
                            in {"coingecko.com", "www.coingecko.com", "docs.coingecko.com"}
                            else "frankfurter"
                            if domain in {"frankfurter.dev", "api.frankfurter.dev"}
                            else None
                        )
                        if fixture:
                            demo_spec, demo_sample = load_fixture(fixture)
                            fetcher = FixtureHTTP(fixture)
                        else:
                            warnings.append(
                                "Demo supports CoinGecko and "
                                "Frankfurter only; paste one of their URLs"
                            )
                            status = "not_found"
                    if cached:
                        hit = True
                        spec = Spec.model_validate(cached["spec"])
                        progress("Loaded archived specification; zero LLM calls")
                        ctx.emit(
                            "prober",
                            "success",
                            "Returned with an archived specification",
                            cache_hit=True,
                        )
                        chunks = [
                            Chunk(
                                source_url=str(endpoint.source_url),
                                markdown=str(spec.base_url) + " " + endpoint.path,
                            )
                            for endpoint in spec.endpoints
                        ]
                    elif status != "not_found":
                        client = DocClient(
                            fetcher, delay=0 if isinstance(fetcher, FixtureHTTP) else 0.2
                        )
                        spec, pages, notes = await Prober().run(ctx, client, url)
                        warnings += notes
                        documents, notes = await Fetcher().run(ctx, client, pages)
                        warnings += notes
                        digest = hashlib.sha256(
                            "\n".join(d.source_url + d.markdown for d in documents).encode()
                        ).hexdigest()
                        if spec:
                            spec.content_hash = digest
                            chunks = [
                                Chunk(source_url=d.source_url, markdown=d.markdown)
                                for d in documents
                            ]
                            ctx.skipped(
                                "retriever", "OpenAPI parsed directly; retrieval not needed"
                            )
                            ctx.skipped(
                                "extractor", "OpenAPI covers these operations; zero LLM calls"
                            )
                        else:
                            chunks = await Retriever().run(ctx, documents)
                            if not chunks or not any(
                                "GET /" in c.markdown
                                or "REST API" in c.markdown
                                or "REST endpoints" in c.markdown
                                for c in chunks
                            ):
                                warnings.append(
                                    "API docs not found. Paste a "
                                    "documentation or OpenAPI URL; no endpoints were guessed"
                                )
                                status = "not_found"
                            else:
                                spec = await Extractor().run(
                                    ctx, provider, chunks, digest, demo_spec
                                )
                    if spec:
                        if not key and not demo and spec.auth.required:
                            host = urlsplit(str(spec.base_url)).hostname
                            key = self.store.credential(host)
                            if key:
                                request.api_key_host = host
                                bus.secrets = [*bus.secrets, key]
                                register_secrets(key)
                        if spec.auth.type == "unsupported":
                            status = "unsupported"
                            warnings.append(
                                spec.unsupported_reason or "Authentication is unsupported"
                            )
                        else:
                            for attempt in range(3):
                                try:
                                    endpoint, sample, note = await Verifier().run(
                                        ctx,
                                        fetcher,
                                        spec,
                                        key=key,
                                        key_host=request.api_key_host,
                                        demo_sample=(
                                            demo_sample
                                            if demo_sample is not None
                                            else self.store.get(
                                                "sample_cache",
                                                spec.endpoints[0].response_sample_ref,
                                            )
                                            if hit
                                            and not request.api_key
                                            and spec.endpoints[0].response_sample_ref
                                            else None
                                        ),
                                    )
                                    if note:
                                        warnings.append(note)
                                    if sample is not None:
                                        profile = await Profiler().run(ctx, sample)
                                        if endpoint:
                                            endpoint.record_path = profile.record_path
                                    else:
                                        ctx.skipped("profiler", "No sample response is available")
                                    status = (
                                        "ready"
                                        if demo or (endpoint and endpoint.verified)
                                        else "unverified"
                                    )
                                    break
                                except VerificationFailed as exc:
                                    if attempt == 2 or not chunks:
                                        warnings.append(
                                            "Verification failed after the bounded repair attempts"
                                        )
                                        status = "unverified"
                                        break
                                    spec = await Repair().run(
                                        ctx, provider, spec, chunks, str(exc), attempt
                                    )
                            if demo:
                                warnings.append(
                                    "Recorded demo examples; endpoints have not been live-verified"
                                )
                        stored_key = cache_key(
                            domain, spec.content_hash, "demo" if demo else "live"
                        )
                        self.store.put(
                            "spec_cache",
                            stored_key,
                            {
                                "spec": spec.model_dump(mode="json"),
                                "usage": cached.get("usage", {})
                                if hit
                                else job.model_dump(mode="json"),
                            },
                        )
                        self.store.index(index_key, stored_key)
                    progress(
                        "Research finished with source-backed results"
                        if spec
                        else "Research finished without guessing API facts"
                    )
            job.status = "success"
        except BudgetExceeded:
            job.status = "waiting"
            status = "budget_blocked"
            warnings.append(
                "Cost Guard blocked the call. Explicit approval is required to raise the budget"
            )
        except ProviderError as exc:
            job.status = "error"
            warnings.append(str(exc))
        except Exception:
            job.status = "error"
            warnings.append(
                "Research failed safely. Check the "
                "documentation URL, connectivity and provider settings"
            )
        job.budget_ready = job.status == "waiting"
        result = ResearchResult(
            job=job,
            status=status,
            spec=spec,
            profile=profile,
            warnings=list(dict.fromkeys(warnings)),
            saved_tokens=cached.get("usage", {}).get("input_tokens", 0) if hit else 0,
            cache_hit=hit,
            demo=demo,
        )
        self.store.save_result(job.id, result.model_dump(mode="json"))
        self.store.save_job(job)
        return result
