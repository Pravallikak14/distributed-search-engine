import asyncio

from crawler.fetcher import Fetcher
from crawler.parser import parse_html
from crawler.url_utils import normalize_url


async def main():
    url = url = "https://example.com/"

    async with Fetcher() as f:
        result = await f.fetch(url)

    if not result.body:
        print("Fetch failed:", result.error)
        return

    page = parse_html(
        result.body,
        result.final_url or url
    )

    normalized = {
        normalized_url
        for link in page.links
        if (normalized_url := normalize_url(link))
    }

    print(f"raw links: {len(page.links)}")
    print(f"unique after normalize: {len(normalized)}")


if __name__ == "__main__":
    asyncio.run(main())