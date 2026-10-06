import asyncio
import os
import statistics
import time

from crawler.bloom import BloomFilter
from crawler.dedupe import ContentDedupe
from crawler.fetcher import Fetcher
from crawler.frontier import Frontier
from crawler.robots import RobotsCache
from crawler.storage import PageStore
from crawler.worker import CrawlStats, worker


DB_PATH = "data/crawl.db"

MAX_PAGES = 10_000
WORKERS = 100


SEEDS = [
    "https://example.com/",
    "https://www.python.org/",
    "https://docs.python.org/3/",
    "https://www.djangoproject.com/",
    "https://flask.palletsprojects.com/",
    "https://fastapi.tiangolo.com/",
    "https://pypi.org/",
    "https://numpy.org/",
    "https://pandas.pydata.org/",
    "https://scikit-learn.org/",
    "https://www.wikipedia.org/",
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "https://developer.mozilla.org/",
    "https://www.w3.org/",
    "https://httpbin.org/",
    "https://www.gnu.org/",
    "https://www.linux.org/",
    "https://www.kernel.org/",
    "https://redis.io/",
    "https://www.postgresql.org/",
    "https://www.docker.com/",
    "https://kubernetes.io/",
    "https://git-scm.com/",
    "https://github.com/",
    "https://docs.github.com/",
    "https://stackoverflow.com/",
    "https://www.rust-lang.org/",
    "https://go.dev/",
    "https://nodejs.org/",
    "https://www.java.com/",
    "https://developer.android.com/",
    "https://kotlinlang.org/",
    "https://react.dev/",
    "https://vuejs.org/",
    "https://angular.dev/",
    "https://www.tensorflow.org/",
    "https://pytorch.org/",
    "https://huggingface.co/",
    "https://www.nasa.gov/",
    "https://www.noaa.gov/",
]


async def progress_report(
    stats,
    store,
    frontier,
    started,
):
    while not frontier.finished:
        await asyncio.sleep(15)

        elapsed = time.perf_counter() - started

        print(
            f"[progress] "
            f"time={elapsed:.0f}s "
            f"pages={stats.pages} "
            f"stored={store.count()} "
            f"duplicates={stats.duplicates} "
            f"errors={stats.errors} "
            f"blocked={stats.blocked} "
            f"queued={frontier.stats['queued']} "
            f"in_flight={frontier.stats['in_flight']}"
        )


async def main():
    os.makedirs("data", exist_ok=True)

    for path in (
        DB_PATH,
        DB_PATH + "-wal",
        DB_PATH + "-shm",
    ):
        if os.path.exists(path):
            os.remove(path)

    frontier = Frontier(
        min_delay=1.0,
        max_depth=3,
        max_per_host=400,
        seen=BloomFilter(1_000_000, 0.01),
    )

    stats = CrawlStats()
    dedupe = ContentDedupe()
    store = PageStore(DB_PATH)

    for seed in SEEDS:
        frontier.add(seed, 0)

    started = time.perf_counter()

    async with Fetcher(
        concurrency=100,
        timeout=10,
        max_retries=3,
    ) as fetcher:

        robots = RobotsCache(fetcher.fetch_text)

        progress = asyncio.create_task(
            progress_report(
                stats,
                store,
                frontier,
                started,
            )
        )

        tasks = [
            asyncio.create_task(
                worker(
                    frontier=frontier,
                    fetcher=fetcher,
                    robots=robots,
                    stats=stats,
                    max_pages=MAX_PAGES,
                    store=store,
                    dedupe=dedupe,
                )
            )
            for _ in range(WORKERS)
        ]

        try:
            await asyncio.gather(*tasks)

        finally:
            frontier.stop()

            if not progress.done():
                progress.cancel()

            await asyncio.gather(
                progress,
                return_exceptions=True,
            )

    # Get database statistics BEFORE closing SQLite.
    stored = store.count()

    raw_bytes = store.raw_bytes
    stored_bytes = store.stored_bytes

    # Now close the database.
    store.close()

    elapsed = time.perf_counter() - started

    throughput = (
        stats.pages / elapsed
        if elapsed > 0
        else 0
    )

    fetch_times = sorted(stats.fetch_times)

    if fetch_times:
        p50 = statistics.median(fetch_times)

        p95_index = min(
            len(fetch_times) - 1,
            int(len(fetch_times) * 0.95),
        )

        p95 = fetch_times[p95_index]
    else:
        p50 = 0
        p95 = 0

    db_size = (
        os.path.getsize(DB_PATH)
        if os.path.exists(DB_PATH)
        else 0
    )

    bloom = frontier._seen

    print()
    print("=" * 60)
    print("10K CRAWL RESULTS")
    print("=" * 60)

    print(f"time:               {elapsed:.1f}s")
    print(f"fetched pages:      {stats.pages}")
    print(f"stored pages:       {stored}")
    print(f"duplicates:         {stats.duplicates}")
    print(f"throughput:         {throughput:.1f} pages/s")
    print(f"hosts:              {len(stats.pages_per_host)}")
    print(f"errors:             {stats.errors}")
    print(f"robots blocked:     {stats.blocked}")
    print(f"p50 fetch latency:  {p50:.3f}s")
    print(f"p95 fetch latency:  {p95:.3f}s")

    if raw_bytes:
        compression_ratio = stored_bytes / raw_bytes

        print(
            f"raw -> gzip:        "
            f"{raw_bytes / 1e6:.1f} MB -> "
            f"{stored_bytes / 1e6:.1f} MB "
            f"({compression_ratio:.1%})"
        )

    print(f"SQLite DB size:     {db_size / 1e6:.1f} MB")
    print(f"Bloom count:        {len(bloom):,}")
    print(
        f"Bloom estimated FP: "
        f"{bloom.estimated_fp_rate():.3%}"
    )

    print()
    print("Top hosts:")

    for host, count in stats.pages_per_host.most_common(10):
        print(f"  {host}: {count}")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())