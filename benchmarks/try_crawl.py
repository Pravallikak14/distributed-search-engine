import asyncio
import time

from crawler.fetcher import Fetcher
from crawler.frontier import Frontier
from crawler.robots import RobotsCache
from crawler.worker import CrawlStats, worker


SEEDS = [
    "https://en.wikipedia.org/wiki/Web_crawler",
    "https://docs.python.org/3/",
    "https://developer.mozilla.org/en-US/",
    "https://go.dev/",
    "https://www.rfc-editor.org/",
]

MAX_PAGES = 300
WORKERS = 30


async def main():
    frontier = Frontier(
        min_delay=1.0,
        max_depth=2,
        max_per_host=60,
    )

    for seed in SEEDS:
        frontier.add(seed)

    stats = CrawlStats()

    t0 = time.monotonic()

    async with Fetcher() as fetcher:
        robots = RobotsCache(fetcher.fetch_text)

        await asyncio.gather(
            *(
                worker(
                    frontier,
                    fetcher,
                    robots,
                    stats,
                    MAX_PAGES,
                )
                for _ in range(WORKERS)
            )
        )

    dt = time.monotonic() - t0

    gaps = [
        b - a
        for timestamps in stats.starts.values()
        for a, b in zip(
            timestamps,
            timestamps[1:],
        )
    ]

    print(
        f"pages={stats.pages} "
        f"errors={stats.errors} "
        f"robots-blocked={stats.blocked}"
    )

    print(
        f"time={dt:.1f}s  "
        f"throughput={stats.pages / dt:.1f} pages/s"
    )

    print(
        f"hosts touched={len(stats.starts)}  "
        f"frontier={frontier.stats}"
    )

    if gaps:
        print(
            f"min gap between requests to same host: "
            f"{min(gaps):.2f}s "
            f"(must be >= 1.0)"
        )


if __name__ == "__main__":
    asyncio.run(main())