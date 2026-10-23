import json
import re
from urllib.parse import urljoin, urlsplit

import httpx
import yaml
from selectolax.parser import HTMLParser

from backend.agents.fetcher import FetchError
from backend.models import Auth, DateParams, Endpoint, Pagination, Param, Spec
from backend.security.ssrf import UnsafeURL, validate_url

CANDIDATES = [
    "/openapi.json",
    "/swagger.json",
    "/openapi.yaml",
    "/docs",
    "/api-docs",
    "/developers",
    "/sitemap.xml",
]


def normalize_url(value):
    url = value.strip()
    if "://" not in url:
        url = "https://" + url
    parts, _ = validate_url(url)
    return parts._replace(netloc=parts.netloc.lower(), path=parts.path or "/").geturl()


def dereference(value, document, depth=0):
    if depth > 8 or not isinstance(value, dict):
        raise ValueError("Unsupported or cyclic schema reference")
    if "$ref" not in value:
        return value
    reference = value["$ref"]
    if not reference.startswith("#/"):
        raise ValueError("External references are not fetched implicitly")
    target = document
    for part in reference[2:].split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    return dereference(target, document, depth + 1)


def parse_auth(document, operation):
    security = operation.get("security", document.get("security", []))
    if not security or {} in security:
        return Auth()
    schemes = document.get("components", {}).get(
        "securitySchemes", document.get("securityDefinitions", {})
    )
    for choice in security:
        if len(choice) != 1:
            continue
        scheme = schemes.get(next(iter(choice)), {})
        kind = scheme.get("type")
        if kind == "apiKey" and scheme.get("in") in {"header", "query"}:
            location = scheme["in"]
            return Auth(required=True, type=location, **{location + "_name": scheme["name"]})
        if kind == "http" and scheme.get("scheme", "").lower() == "bearer":
            return Auth(required=True, type="bearer")
    return Auth(required=True, type="unsupported")


def dates(parameters):
    candidates = [
        p
        for p in parameters
        if p.name in {"date", "from", "to", "start", "end", "start_date", "end_date"}
        and (
            "date" in p.description.lower()
            or "timestamp" in p.description.lower()
            or "unix" in p.description.lower()
        )
    ]
    start = next((p for p in candidates if p.name in {"from", "start", "start_date", "date"}), None)
    end = next((p for p in candidates if p.name in {"to", "end", "end_date"}), None)
    if not start:
        return None
    fmt = (
        "unix_ms"
        if "millisecond" in start.description.lower()
        else "unix"
        if "unix" in start.description.lower()
        else "iso"
    )
    return DateParams(start=start.name, end=end.name if end else None, format=fmt)


def parse_openapi(body, source_url):
    try:
        document = json.loads(body) if body.lstrip().startswith(b"{") else yaml.safe_load(body)
    except (ValueError, yaml.YAMLError):
        return None, []
    if not isinstance(document, dict) or not (document.get("openapi") or document.get("swagger")):
        return None, []
    parts = urlsplit(source_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if document.get("swagger"):
        scheme = document.get("schemes", [parts.scheme])[0]
        host = document.get("host", parts.netloc)
        base = f"{scheme}://{host}{document.get('basePath', '')}"
    else:
        server = document.get("servers", [{"url": origin}])[0].get("url", origin)
        if "{" in server:
            return None, ["OpenAPI server variables require an explicit server URL"]
        base = urljoin(source_url, server)
    endpoints, warnings, selected_auth = [], [], None
    for path, raw_path in list(document.get("paths", {}).items())[:200]:
        try:
            item = dereference(raw_path, document)
            for method, raw_operation in item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete", "head"}:
                    continue
                operation = dereference(raw_operation, document)
                if operation.get("servers") or item.get("servers"):
                    warnings.append(
                        "Operation-specific servers omitted; use their OpenAPI URL separately"
                    )
                    continue
                auth = parse_auth(document, operation)
                if selected_auth is not None and auth != selected_auth:
                    warnings.append("Endpoints with different authentication omitted as unverified")
                    continue
                parameters = {}
                for raw_param in item.get("parameters", []) + operation.get("parameters", []):
                    param = dereference(raw_param, document)
                    if param.get("in") not in {"query", "path", "header", "body"}:
                        continue
                    schema = dereference(param.get("schema", param), document)
                    parameters[(param["name"], param["in"])] = Param(
                        name=param["name"],
                        location=param["in"],
                        required=param.get("required", False),
                        type=schema.get("type", "string"),
                        default=schema.get("default"),
                        description=param.get("description", "")
                        + (" date" if schema.get("format") in {"date", "date-time"} else ""),
                        allowed_values=schema.get("enum"),
                    )
                values = list(parameters.values())
                pagination = next(
                    (
                        Pagination(type=p.name if p.name != "page" else "page", param=p.name)
                        for p in values
                        if p.name in {"page", "offset", "cursor"}
                    ),
                    None,
                )
                endpoints.append(
                    Endpoint(
                        path=path,
                        method=method.upper(),
                        description=operation.get("summary", operation.get("description", ""))[
                            :1000
                        ],
                        source_url=source_url,
                        params=values,
                        date_params=dates(values),
                        pagination=pagination,
                    )
                )
                selected_auth = auth
        except (ValueError, KeyError, TypeError):
            warnings.append("An unsupported OpenAPI operation was omitted as unverified")
    if not endpoints:
        return None, warnings
    name = (
        re.sub(r"\W+", "_", document.get("info", {}).get("title", "api")).strip("_").lower()
        or "api"
    )
    if name[0].isdigit():
        name = "api_" + name
    return Spec(
        name=name,
        base_url=base,
        docs_urls=[source_url],
        content_hash="pending",
        auth=selected_auth or Auth(),
        endpoints=endpoints,
    ), warnings


class Prober:
    async def run(self, ctx, client, url):
        pages, warnings, seen = [], [], set()
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        queue = [url] + [origin + path for path in CANDIDATES]
        async with ctx.step("prober", "Discover API documentation") as progress:
            while queue and len(seen) < 24:
                candidate = queue.pop(0)
                if candidate in seen:
                    continue
                seen.add(candidate)
                try:
                    body = await client.raw(candidate)
                    spec, notes = parse_openapi(body, candidate)
                    warnings.extend(notes)
                    if spec:
                        progress(
                            f"Parsed {len(spec.endpoints)} documented operations without an LLM"
                        )
                        return spec, [(candidate, body)], warnings
                    tree = HTMLParser(body.decode(errors="replace"))
                    for node in tree.css("a[href],link[href]"):
                        link = node.attributes.get("href", "")
                        if re.search(r"api|developer|docs|openapi|swagger", link, re.IGNORECASE):
                            linked = urljoin(candidate, link).split("#")[0]
                            if linked not in seen:
                                queue.append(linked)
                    if "sitemap" in urlsplit(candidate).path:
                        queue += re.findall(
                            r"<loc>(https?://[^<]+)</loc>", body.decode(errors="replace")
                        )[:12]
                    if (
                        b"REST API" in body
                        or b"GET /" in body
                        or candidate == url
                        or re.search(r"docs|developer|api-docs", urlsplit(candidate).path)
                    ):
                        pages.append((candidate, body))
                except (httpx.HTTPError, FetchError, UnsafeURL, TimeoutError, ValueError):
                    continue
            progress(f"Found {len(pages)} possible documentation pages")
        return None, pages, warnings
