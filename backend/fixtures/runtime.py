import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from backend.models import Spec

ROOT = Path(__file__).parent


def load_fixture(name):
    if name not in {"coingecko", "frankfurter"}:
        raise ValueError("Unknown demo fixture; choose CoinGecko or Frankfurter")
    directory = ROOT / name
    return (
        Spec.model_validate_json((directory / "spec.json").read_text()),
        json.loads((directory / "sample.json").read_text()),
    )


class FixtureHTTP:
    def __init__(self, name, *, openapi=True, failures=0, not_found=False):
        self.name, self.openapi, self.failures = name, openapi, failures
        self.not_found = not_found
        self.requests = []

    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        request = httpx.Request("GET", url)
        path = urlsplit(url).path
        directory = ROOT / self.name
        if path == "/robots.txt":
            return b"User-agent: *\nAllow: /"
        if not self.not_found:
            if (
                self.name == "frankfurter"
                and self.openapi
                and path in {"/openapi.json", "/v2/openapi.json"}
            ):
                return (directory / "openapi.json").read_bytes()
            if path == "/" and urlsplit(url).hostname in {"coingecko.com", "www.coingecko.com"}:
                return (
                    b'<a href="https://docs.coingecko.com/demo/reference/'
                    b'coins-id-market-chart-range">API docs</a>'
                )
            if path == "/demo/reference/coins-id-market-chart-range" or (
                self.name == "frankfurter" and path == "/"
            ):
                return (directory / "docs.md").read_bytes()
            if path.endswith("/rates") or "/market_chart/range" in path:
                if self.failures:
                    self.failures -= 1
                    response = httpx.Response(400, request=request)
                    raise httpx.HTTPStatusError(
                        "Recorded failure", request=request, response=response
                    )
                return (directory / "sample.json").read_bytes()
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("Recorded not found", request=request, response=response)
