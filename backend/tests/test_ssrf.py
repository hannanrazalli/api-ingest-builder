import asyncio

import httpx
import pytest

from backend.security.ssrf import PinnedTransport, SafeFetcher, UnsafeURL, public_addresses


async def public(host, port):
    return ["93.184.216.34"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com",
        "http://user:pass@example.com",
        "http://example.com/#x",
        "http://example.com:99999",
    ],
)
def test_bad_urls(url):
    with pytest.raises((UnsafeURL, ValueError)):
        asyncio.run(public_addresses(url, public))


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "172.16.0.1",
        "192.168.1.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "64:ff9b::a00:1",
        "2002:0a00:0001::",
        "224.0.0.1",
        "0.0.0.0",
    ],
)
def test_private_and_mixed_dns_blocked(ip):
    async def resolver(host, port):
        return ["93.184.216.34", ip]

    with pytest.raises(UnsafeURL):
        asyncio.run(public_addresses("https://example.com", resolver))


class Bytes(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"abcd"
        yield b"efgh"


def test_size_limit_redirect_revalidation_and_no_credentials():
    async def resolver(host, port):
        return ["127.0.0.1"] if host == "private.test" else ["93.184.216.34"]

    def redirect(request):
        return httpx.Response(302, headers={"location": "http://private.test/metadata"})

    fetcher = SafeFetcher(
        resolver=resolver, transport_factory=lambda ip: httpx.MockTransport(redirect)
    )
    with pytest.raises(UnsafeURL):
        asyncio.run(fetcher.get("https://example.com"))
    with pytest.raises(UnsafeURL):
        asyncio.run(fetcher.get("https://example.com", headers={"X-Key": "secret"}))
    with pytest.raises(UnsafeURL):
        asyncio.run(
            fetcher.get(
                "https://example.com", headers={"X-Key": "secret"}, credential_host="other.example"
            )
        )
    fetcher = SafeFetcher(
        max_bytes=4,
        resolver=public,
        transport_factory=lambda ip: httpx.MockTransport(
            lambda r: httpx.Response(200, stream=Bytes())
        ),
    )
    with pytest.raises(UnsafeURL, match="size"):
        asyncio.run(fetcher.get("https://example.com"))


def test_redirect_cap_and_cross_host_key_block():
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://other.example/next"})

    fetcher = SafeFetcher(
        max_redirects=1, resolver=public, transport_factory=lambda ip: httpx.MockTransport(redirect)
    )
    with pytest.raises(UnsafeURL, match="Redirect"):
        asyncio.run(fetcher.get("https://example.com"))
    assert len(requests) == 2
    requests.clear()
    with pytest.raises(UnsafeURL, match="Credentials"):
        asyncio.run(
            fetcher.get(
                "https://example.com",
                headers={"Authorization": "secret"},
                credential_host="example.com",
            )
        )
    assert len(requests) == 1


def test_timeout_and_success():
    async def slow(host, port):
        await asyncio.sleep(1)
        return ["93.184.216.34"]

    with pytest.raises(TimeoutError):
        asyncio.run(SafeFetcher(timeout=0.01, resolver=slow).get("https://example.com"))
    fetcher = SafeFetcher(
        resolver=public,
        transport_factory=lambda ip: httpx.MockTransport(
            lambda r: httpx.Response(200, stream=Bytes())
        ),
    )
    assert asyncio.run(fetcher.get("https://example.com")) == b"abcdefgh"


def test_pinned_transport_preserves_host_and_sni():
    transport = PinnedTransport("93.184.216.34")

    async def run():
        await transport.inner.aclose()

        async def inspect(request):
            assert request.url.host == "93.184.216.34"
            assert request.headers["host"] == "example.com"
            assert request.extensions["sni_hostname"] == "example.com"
            return httpx.Response(200)

        transport.inner = httpx.MockTransport(inspect)
        async with httpx.AsyncClient(transport=transport) as client:
            assert (await client.get("https://example.com/path")).status_code == 200

    asyncio.run(run())


def test_query_key_redirect_and_tls_downgrade_blocked():
    seen = []

    def redirect(request):
        seen.append(request)
        assert request.url.params["api_key"] == "fake-query-secret"
        return httpx.Response(302, headers={"location": "http://example.com/next"})

    fetcher = SafeFetcher(
        resolver=public, transport_factory=lambda ip: httpx.MockTransport(redirect)
    )
    with pytest.raises(UnsafeURL, match="downgrade"):
        asyncio.run(
            fetcher.get(
                "https://example.com",
                params={"api_key": "fake-query-secret"},
                credential_host="example.com",
            )
        )
    assert len(seen) == 1


def test_compressed_response_rejected():
    fetcher = SafeFetcher(
        resolver=public,
        transport_factory=lambda ip: httpx.MockTransport(
            lambda r: httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Bytes())
        ),
    )
    with pytest.raises(UnsafeURL, match="Compressed"):
        asyncio.run(fetcher.get("https://example.com"))
