import asyncio

from crawler.fetcher import Fetcher
from crawler.robots import RobotsCache


URLS = [
    "https://en.wikipedia.org/wiki/Web_crawler",
    "https://en.wikipedia.org/w/index.php?title=Web_crawler&action=edit",
    "https://www.google.com/search?q=python",
    "https://www.google.com/about",
    "https://example.com/",
    "https://this-domain-does-not-exist-xyz.com/",
]


async def main():
    async with Fetcher() as f:
        robots = RobotsCache(f.fetch_text)

        for url in URLS:
            ok = await robots.is_allowed(url)
            delay = await robots.crawl_delay(url)

            print(
                f"{'ALLOW' if ok else 'BLOCK':5}  "
                f"delay={delay}  {url}"
            )


if __name__ == "__main__":
    asyncio.run(main())