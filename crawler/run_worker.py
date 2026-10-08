import argparse
import asyncio
import json
from pathlib import Path

import redis.asyncio as aioredis

from crawler.dedupe import ContentDedupe
from crawler.fetcher import Fetcher
from crawler.redis_frontier import RedisFrontier
from crawler.robots import RobotsCache
from crawler.storage import PageStore
from crawler.worker import CrawlStats, worker


async def main(a):
    Path("data").mkdir(exist_ok=True)

    r = aioredis.Redis.from_url(
        a.redis,
        decode_responses=True,
    )

    frontier = RedisFrontier(
        r,
        max_depth=a.max_depth,
        max_per_host=a.max_per_host,
    )

    await frontier.connect()

    stats = CrawlStats()
    dedupe = ContentDedupe()

    store = PageStore(
        f"data/crawl-{a.id}.db"
    )

    try:
        async with Fetcher() as f:
            robots = RobotsCache(
                f.fetch_text
            )

            await asyncio.gather(
                *(
                    worker(
                        frontier,
                        f,
                        robots,
                        stats,
                        a.max_pages,
                        store,
                        dedupe,
                    )
                    for _ in range(a.workers)
                )
            )

    finally:
        store.close()
        await r.aclose()

    summary = {
        "id": a.id,
        "pages": stats.pages,
        "duplicates": stats.duplicates,
        "errors": stats.errors,
        "blocked": stats.blocked,
        "error_kinds": dict(
            stats.error_kinds
        ),
        "fetch_times": stats.fetch_times,
        "starts": stats.starts,
        "raw_bytes": store.raw_bytes,
        "stored_bytes": store.stored_bytes,
    }

    Path(
        f"data/stats-{a.id}.json"
    ).write_text(
        json.dumps(summary)
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--id",
        type=int,
        default=0,
    )

    ap.add_argument(
        "--workers",
        type=int,
        default=50,
    )

    ap.add_argument(
        "--max-pages",
        type=int,
        default=10_000,
    )

    ap.add_argument(
        "--max-depth",
        type=int,
        default=3,
    )

    ap.add_argument(
        "--max-per-host",
        type=int,
        default=400,
    )

    ap.add_argument(
        "--redis",
        default="redis://localhost:6379/0",
    )

    asyncio.run(
        main(ap.parse_args())
    )