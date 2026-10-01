import asyncio
from crawler.fetcher import Fetcher

URLS = [
    "https://en.wikipedia.org/wiki/Web_crawler",
    "https://en.wikipedia.org/wiki/Search_engine",
    "https://docs.python.org/3/",
    "https://example.com",
    "https://httpbin.org/status/404",
    "https://httpbin.org/status/503",
    "https://httpbin.org/delay/15",
    "https://this-domain-does-not-exist-xyz.com",
]


async def main():
    async with Fetcher() as f:
        results = await asyncio.gather(*(f.fetch(url) for url in URLS))

    for r in results:
        size = len(r.body) if r.body else 0
        print(
            f"{r.status or '-':>4} "
            f"{r.elapsed:5.1f}s "
            f"{size:>8}B "
            f"{r.error or 'ok':<18} "
            f"{r.url}"
        )


asyncio.run(main())