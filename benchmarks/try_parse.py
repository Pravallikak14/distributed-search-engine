import asyncio

from crawler.fetcher import Fetcher
from crawler.parser import parse_html


URLS = [
    "https://en.wikipedia.org/wiki/Web_crawler",
    "https://docs.python.org/3/",
    "https://example.com",
]


async def main():
    async with Fetcher() as f:
        results = await asyncio.gather(*(f.fetch(u) for u in URLS))

    for r in results:
        if not r.body:
            print("FAILED", r.url, r.error)
            continue

        p = parse_html(r.body, r.final_url or r.url)

        print(
            f"{p.title[:40]!r:45} "
            f"text={len(p.text):>7} chars  "
            f"links={len(p.links):>4}  "
            f"{r.url}"
        )

        print("   sample links:", p.links[:3])


asyncio.run(main())