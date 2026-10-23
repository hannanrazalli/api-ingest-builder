from backend.models import Spec
from backend.models.research import Extraction
from backend.security.ssrf import validate_url


def validate_spec(spec, chunks):
    sources = {chunk.source_url for chunk in chunks}
    evidence = "\n".join(chunk.markdown for chunk in chunks)
    if str(spec.base_url).rstrip("/") not in evidence:
        raise ValueError("The API base URL is not supported by the retrieved evidence")
    validate_url(str(spec.base_url))
    for endpoint in spec.endpoints:
        if str(endpoint.source_url) not in sources or endpoint.path not in evidence:
            raise ValueError("An endpoint has no retrieved source evidence")
        if endpoint.path.startswith("//") or any(c in endpoint.path for c in ("?", "#", "\\")):
            raise ValueError("Unsafe endpoint path")
        endpoint.verified = False
    if any(
        "\n" in key + value or "\r" in key + value for key, value in spec.default_headers.items()
    ):
        raise ValueError("Invalid header")
    if any(
        key.lower() not in {"accept", "content-type", "user-agent"} for key in spec.default_headers
    ):
        raise ValueError("Credentials cannot be supplied as default headers")
    return spec


def to_spec(extraction, chunks, content_hash):
    values = extraction.model_dump(mode="json", exclude={"headers"})
    values["default_headers"] = {header.name: header.value for header in extraction.headers}
    values["docs_urls"] = sorted({chunk.source_url for chunk in chunks})
    values["content_hash"] = content_hash
    spec = Spec.model_validate(values)
    return validate_spec(spec, chunks)


class Extractor:
    async def run(self, ctx, provider, chunks, digest, demo_spec=None):
        async with ctx.step("extractor", "Extract a source-backed API specification") as progress:
            progress(f"Use {len(chunks)} retrieved chunks only")
            if demo_spec is not None:
                progress("Use recorded specification; no live LLM request")
                spec = demo_spec.model_copy(deep=True)
                spec.content_hash = digest
                return validate_spec(spec, chunks)
            text = (
                "Extract documented REST endpoints. Return sources exactly as supplied.\n"
                + "\n".join(f"SOURCE_URL: {chunk.source_url}\n{chunk.markdown}" for chunk in chunks)
            )
            result = await provider.structured("extractor", text, Extraction, max_output=2000)
            return to_spec(result, chunks, digest)
