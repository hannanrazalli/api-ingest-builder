import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit

import httpx

from backend.cache.store import cache_key
from backend.security.redaction import redact
from backend.security.ssrf import UnsafeURL


class VerificationFailed(ValueError):
    pass


class Verifier:
    async def run(self, ctx, fetcher, spec, *, key=None, key_host=None, demo_sample=None):
        async with ctx.step("verifier", "Verify one safe GET operation") as progress:
            endpoint = next((item for item in spec.endpoints if item.method == "GET"), None)
            if endpoint is None or spec.auth.type == "unsupported":
                progress("No supported GET operation can be verified")
                return None, None, "No supported GET operation is available"
            if demo_sample is not None:
                progress("Use recorded response example; not a live verification")
                sample = demo_sample
            else:
                if spec.auth.required and not key:
                    progress("API credentials required; endpoint remains unverified")
                    return endpoint, None, "Supply the API key for this API host to verify"
                if key and key_host != urlsplit(str(spec.base_url)).hostname:
                    raise UnsafeURL("API key host does not match the documented API base URL")
                params, headers, path = {}, dict(spec.default_headers), endpoint.path
                day = datetime.now(UTC) - timedelta(days=1)
                date_values = {}
                if endpoint.date_params:
                    dates = endpoint.date_params
                    for name in (dates.start, dates.end):
                        if name:
                            date_values[name] = (
                                int(day.timestamp()) * (1000 if dates.format == "unix_ms" else 1)
                                if dates.format in {"unix", "unix_ms"}
                                else day.strftime(dates.strftime or "%Y-%m-%d")
                            )
                for param in endpoint.params:
                    value = date_values.get(param.name, param.default)
                    if value is None and param.required:
                        progress("A required parameter needs a user value")
                        return (
                            endpoint,
                            None,
                            "Required parameters have no documented default; verification skipped",
                        )
                    if value is None:
                        continue
                    if param.location == "path":
                        path = path.replace("{" + param.name + "}", quote(str(value), safe=""))
                    elif param.location == "query":
                        params[param.name] = value
                    elif param.location == "header":
                        headers[param.name] = str(value)
                if re.search(r"{[^}]+}", path):
                    return endpoint, None, "Path parameters require user values"
                if key:
                    if spec.auth.type == "header":
                        headers[spec.auth.header_name] = key
                    elif spec.auth.type == "query":
                        params[spec.auth.query_name] = key
                    elif spec.auth.type == "bearer":
                        headers["Authorization"] = "Bearer " + key
                if path.startswith("//") or "\\" in path or "?" in path or "#" in path:
                    raise UnsafeURL("Unsafe endpoint path")
                url = str(spec.base_url).rstrip("/") + "/" + path.lstrip("/")
                try:
                    body = await fetcher.get(
                        url,
                        headers=headers or None,
                        params=params or None,
                        credential_host=urlsplit(str(spec.base_url)).hostname,
                    )
                    sample = json.loads(body)
                    if not isinstance(sample, (dict, list)) or (
                        isinstance(sample, dict) and (sample.get("error") or sample.get("errors"))
                    ):
                        raise VerificationFailed(
                            "GET response does not contain usable JSON records"
                        )
                    endpoint.verified = True
                except httpx.HTTPStatusError as exc:
                    raise VerificationFailed(
                        f"GET returned HTTP {exc.response.status_code}"
                    ) from None
                except (httpx.HTTPError, ValueError, TimeoutError):
                    raise VerificationFailed(
                        "GET response failed schema/date/parameter verification"
                    ) from None
                progress(
                    "GET returned valid JSON; parameter acceptance is observational, not guaranteed"
                )
            sample = redact(sample, ctx.bus.secrets)
            reference = cache_key(spec.content_hash, endpoint.path, "sample")
            ctx.store.put("sample_cache", reference, sample)
            endpoint.response_sample_ref = reference
            return endpoint, sample, None
