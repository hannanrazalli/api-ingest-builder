import asyncio
import hashlib
import importlib.util
import time
from urllib.robotparser import RobotFileParser

import httpx
from markdownify import markdownify
from selectolax.parser import HTMLParser

from backend.models.research import Document
from backend.security.ssrf import SafeFetcher, UnsafeURL, validate_url


class FetchError(ValueError):
    pass


class DocClient:
    def __init__(self, fetcher=None, delay=0.2, max_requests=48):
        self.fetcher = fetcher or SafeFetcher()
        self.delay, self.max_requests = delay, max_requests
        self.requests = 0
        self.robots = {}
        self.last = {}
        self.bodies = {}

    async def raw(self, url):
        if url in self.bodies:
            return self.bodies[url]
        parts, _ = validate_url(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            parser = RobotFileParser()
            try:
                content = await self._get(origin + "/robots.txt")
                parser.parse(content.decode(errors="replace").splitlines())
            except httpx.HTTPStatusError as exc:
                parser.parse(
                    ["User-agent: *", "Disallow: /"] if exc.response.status_code != 404 else []
                )
            self.robots[origin] = parser
        parser = self.robots[origin]
        if not parser.can_fetch("APIIngestBuilder", url):
            raise FetchError("Documentation is disallowed by robots.txt")
        interval = max(self.delay, parser.crawl_delay("APIIngestBuilder") or 0)
        rate = parser.request_rate("APIIngestBuilder")
        if rate and rate.requests:
            interval = max(interval, rate.seconds / rate.requests)
        await asyncio.sleep(max(0, interval - (time.monotonic() - self.last.get(origin, 0))))
        try:
            body = await self._get(url)
        finally:
            self.last[origin] = time.monotonic()
        self.bodies[url] = body
        return body

    async def _get(self, url):
        if self.requests >= self.max_requests:
            raise FetchError("Documentation request limit reached")
        self.requests += 1
        return await self.fetcher.get(url)


def clean_markdown(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    if "<" in text and ">" in text:
        tree = HTMLParser(text)
        for node in tree.css("nav,footer,header,script,style,aside,noscript"):
            node.decompose()
        text = markdownify(tree.html or "", heading_style="ATX")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())[:100_000]


class JSRenderer:
    async def render(self, url, client):
        if importlib.util.find_spec("playwright") is None:
            raise FetchError(
                "JavaScript docs require optional Playwright; "
                "use the js profile or paste a static/OpenAPI URL"
            )
        from playwright.async_api import async_playwright

        async with async_playwright() as runtime:
            browser = await runtime.chromium.launch(headless=True)
            try:
                context = await browser.new_context(service_workers="block")
                await context.set_offline(True)
                await context.add_init_script(
                    "for (const key of ['RTCPeerConnection', 'webkitRTCPeerConnection', "
                    "'WebTransport', 'Worker', 'SharedWorker']) { "
                    "Object.defineProperty(globalThis, key, {value: undefined, "
                    "configurable: false, writable: false}); }"
                )

                # All browser network requests are fulfilled through the protected GET client.
                async def route(request_route):
                    request = request_route.request
                    if request.method != "GET" or request.resource_type not in {
                        "document",
                        "script",
                        "stylesheet",
                        "xhr",
                        "fetch",
                    }:
                        await request_route.abort()
                        return
                    try:
                        body = await client.raw(request.url)
                        content_type = {
                            "document": "text/html",
                            "script": "application/javascript",
                            "stylesheet": "text/css",
                        }.get(request.resource_type, "application/json")
                        await request_route.fulfill(
                            body=body,
                            content_type=content_type,
                            headers={
                                "Content-Security-Policy": "default-src 'none'; "
                                "script-src 'unsafe-inline' 'unsafe-eval' http: https:; "
                                "style-src 'unsafe-inline' http: https:; connect-src 'none'; "
                                "worker-src 'none'; frame-src 'none'"
                            },
                        )
                    except Exception:
                        await request_route.abort()

                await context.route("**/*", route)
                if not hasattr(context, "route_web_socket"):
                    raise FetchError(
                        "Update optional Playwright to support protected browser networking"
                    )
                await context.route_web_socket("**/*", lambda socket: socket.close())
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=15000)
                return (await page.content()).encode()
            finally:
                await browser.close()


class Fetcher:
    async def run(self, ctx, client, pages, renderer=None):
        documents, hashes, warnings = [], set(), []
        async with ctx.step("fetcher", "Fetch and clean documentation") as progress:
            for url, body in pages[:12]:
                markdown = clean_markdown(body)
                if len(markdown) < 80 and any(
                    token in body.lower() for token in (b"<script", b"javascript")
                ):
                    try:
                        markdown = clean_markdown(
                            await (renderer or JSRenderer()).render(url, client)
                        )
                    except (FetchError, UnsafeURL, TimeoutError):
                        warnings.append(
                            "JavaScript documentation unavailable; install "
                            "the optional js profile or paste static/OpenAPI docs"
                        )
                digest = hashlib.sha256(markdown.encode()).hexdigest()
                if markdown and digest not in hashes:
                    documents.append(Document(source_url=url, markdown=markdown))
                    hashes.add(digest)
            progress(f"Kept {len(documents)} unique documentation pages")
        return documents, warnings
