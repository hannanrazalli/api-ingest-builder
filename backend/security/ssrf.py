import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx


class UnsafeURL(ValueError):
    pass


async def resolve(host: str, port: int) -> list[str]:
    rows = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    return sorted({row[4][0] for row in rows})


def validate_url(url: str):
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise UnsafeURL("Only HTTP(S) URLs without credentials or fragments are allowed")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise UnsafeURL("Invalid port") from None
    return parts, port


async def public_addresses(url: str, resolver=resolve) -> list[str]:
    parts, port = validate_url(url)
    addresses = await resolver(parts.hostname, port)
    if not addresses:
        raise UnsafeURL("Host did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        translated = isinstance(ip, ipaddress.IPv6Address) and any(
            ip in ipaddress.ip_network(network)
            for network in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
        )
        if not ip.is_global or ip.is_multicast or getattr(ip, "ipv4_mapped", None) or translated:
            raise UnsafeURL("Private, reserved, and metadata addresses are blocked")
    return addresses


class PinnedTransport(httpx.AsyncBaseTransport):
    """Connect to the validated address; retain original Host and TLS certificate/SNI."""

    def __init__(self, address: str):
        self.address = address
        self.inner = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        hostname = request.url.host
        request.extensions["sni_hostname"] = hostname
        request.url = request.url.copy_with(host=self.address)
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


class SafeFetcher:
    def __init__(
        self,
        max_bytes=2_000_000,
        timeout=15,
        max_redirects=4,
        resolver=resolve,
        transport_factory=PinnedTransport,
    ):
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.resolver = resolver
        self.transport_factory = transport_factory

    async def get(
        self, url: str, *, headers=None, params=None, credential_host: str | None = None
    ) -> bytes:
        # Callers supplying API credentials must bind them to the spec base_url hostname.
        if (headers or params) and credential_host is None:
            raise UnsafeURL("Headers and parameters require an explicit credential host")
        if params:
            url = str(httpx.URL(url).copy_merge_params(params))
        original_scheme = urlsplit(url).scheme
        async with asyncio.timeout(self.timeout):
            for hop in range(self.max_redirects + 1):
                parts, _ = validate_url(url)
                if (headers or params) and parts.hostname != credential_host:
                    raise UnsafeURL("Credentials cannot leave the spec base_url host")
                if (headers or params) and original_scheme == "https" and parts.scheme != "https":
                    raise UnsafeURL("Credentials cannot follow an HTTPS downgrade")
                addresses = await public_addresses(url, self.resolver)
                request_headers = {"Accept-Encoding": "identity", **(headers or {})}
                async with httpx.AsyncClient(
                    transport=self.transport_factory(addresses[0]),
                    follow_redirects=False,
                    trust_env=False,
                    timeout=self.timeout,
                ) as client:
                    async with client.stream("GET", url, headers=request_headers) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if hop == self.max_redirects or not response.headers.get("location"):
                                raise UnsafeURL("Redirect limit or invalid redirect")
                            url = urljoin(url, response.headers["location"])
                            continue
                        response.raise_for_status()
                        if response.headers.get("content-encoding", "identity") != "identity":
                            raise UnsafeURL("Compressed responses are disabled to bound memory")
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body) + len(chunk) > self.max_bytes:
                                raise UnsafeURL("Response exceeds size limit")
                            body.extend(chunk)
                        return bytes(body)
        raise UnsafeURL("Fetch failed")
