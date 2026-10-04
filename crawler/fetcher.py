import asyncio
import random
from dataclasses import dataclass

import aiohttp


BOT_TOKEN = "MySearchBot"
USER_AGENT = f"{BOT_TOKEN}/0.1 (your-email@example.com)"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_BYTES = 2_000_000


@dataclass
class FetchResult:
    url: str
    final_url: str | None = None
    status: int | None = None
    body: str | None = None
    error: str | None = None
    elapsed: float = 0.0


class Fetcher:
    def __init__(self, concurrency=50, timeout=10, max_retries=3):
        self._sem = asyncio.Semaphore(concurrency)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._max_retries = max_retries
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
        )
        return self

    async def __aexit__(self, *exc):
        await self._session.close()

    async def fetch(self, url: str) -> FetchResult:
        async with self._sem:
            return await self._fetch_with_retries(url)

    async def _fetch_with_retries(self, url: str) -> FetchResult:
        loop = asyncio.get_running_loop()
        start = loop.time()
        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                async with self._session.get(
                    url,
                    max_redirects=5,
                ) as resp:

                    ctype = resp.headers.get("Content-Type", "")

                    if resp.status in RETRY_STATUS:
                        last_error = f"HTTP {resp.status}"

                    elif "text/html" not in ctype:
                        return FetchResult(
                            url,
                            str(resp.url),
                            resp.status,
                            error="non-html",
                            elapsed=loop.time() - start,
                        )

                    else:
                        raw = await resp.content.read(MAX_BYTES)

                        body = raw.decode(
                            resp.charset or "utf-8",
                            errors="replace",
                        )

                        return FetchResult(
                            url,
                            str(resp.url),
                            resp.status,
                            body,
                            elapsed=loop.time() - start,
                        )

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = type(e).__name__

            if attempt < self._max_retries:
                await asyncio.sleep(
                    2 ** attempt + random.random()
                )

        return FetchResult(
            url,
            error=last_error,
            elapsed=loop.time() - start,
        )
    async def fetch_text(self, url: str, max_bytes: int = 500_000):
        """Raw fetch for text files such as robots.txt."""

        async with self._sem:
            try:
                async with self._session.get(
                    url,
                    max_redirects=5
                ) as resp:
                    raw = await resp.content.read(max_bytes)

                    return (
                        resp.status,
                        raw.decode(
                            resp.charset or "utf-8",
                            errors="replace"
                        )
                    )

            except (aiohttp.ClientError, asyncio.TimeoutError):
                return None, None
