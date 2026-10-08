import argparse
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

import redis.asyncio as aioredis

from benchmarks.seeds import SEEDS
from crawler.redis_frontier import RedisFrontier


DATA = Path("data")


async def progress(frontier, t0):
    while True:
        await asyncio.sleep(15)

        print(
            f"[{time.monotonic() - t0:4.0f}s] "
            f"{await frontier.stats()}"
        )


async def main(a):
    DATA.mkdir(exist_ok=True)

    # Remove old distributed crawl data
    for old in [
        *DATA.glob("crawl-*"),
        *DATA.glob("stats-*.json"),
    ]:
        old.unlink()

    r = aioredis.Redis.from_url(
        "redis://localhost:6379/0",
        decode_responses=True,
    )

    frontier = RedisFrontier(
        r,
        max_depth=3,
        max_per_host=400,
    )

    # Fresh Redis frontier for this benchmark
    await frontier.reset()
    await frontier.connect()

    seeded = await frontier.add_many(SEEDS)

    print(
        f"seeded {seeded} URLs, "
        f"starting {a.procs} processes "
        f"x {a.workers} workers"
    )

    t0 = time.monotonic()

    # Start multiple crawler processes
    procs = [
        await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "crawler.run_worker",
            "--id",
            str(i),
            "--workers",
            str(a.workers),
            "--max-pages",
            str(a.max_pages),
            "--max-depth",
            "3",
            "--max-per-host",
            "400",
        )
        for i in range(a.procs)
    ]

    reporter = asyncio.create_task(
        progress(frontier, t0)
    )

    await asyncio.gather(
        *(p.wait() for p in procs)
    )

    reporter.cancel()

    dt = time.monotonic() - t0

    final = await frontier.stats()

    await r.aclose()

    # -------------------------
    # Aggregate results
    # -------------------------

    sums = [
        json.loads(p.read_text())
        for p in sorted(
            DATA.glob("stats-*.json")
        )
    ]

    pages = sum(
        s["pages"]
        for s in sums
    )

    dups = sum(
        s["duplicates"]
        for s in sums
    )

    times = sorted(
        t
        for s in sums
        for t in s["fetch_times"]
    )

    def pct(q):
        if not times:
            return 0.0

        return times[
            min(
                len(times) - 1,
                int(len(times) * q),
            )
        ]

    # Merge request start times
    # from all processes.
    starts: dict[str, list[float]] = {}

    for s in sums:
        for host, ts in s["starts"].items():
            starts.setdefault(
                host,
                []
            ).extend(ts)

    gaps = [
        b - a_
        for ts in starts.values()
        for a_, b in zip(
            sorted(ts),
            sorted(ts)[1:],
        )
    ]

    # Read all SQLite databases
    urls = []

    for db in sorted(
        DATA.glob("crawl-*.db")
    ):
        con = sqlite3.connect(db)

        urls += [
            u
            for (u,) in con.execute(
                "SELECT url FROM pages"
            )
        ]

        con.close()

    # -------------------------
    # Results
    # -------------------------

    print("\n===== RESULTS =====")

    print(
        f"procs={a.procs} "
        f"workers/proc={a.workers} "
        f"time={dt:.0f}s"
    )

    print(
        f"fetched={pages} "
        f"duplicates={dups} "
        f"throughput={pages / dt:.1f} pages/s "
        f"hosts={len(starts)}"
    )

    print(
        "pages per process: "
        f"{[s['pages'] for s in sums]}"
    )

    print(
        f"fetch latency "
        f"p50={pct(0.5):.2f}s "
        f"p95={pct(0.95):.2f}s"
    )

    print(
        f"stored rows={len(urls)} "
        f"unique URLs={len(set(urls))} "
        f"(must be equal)"
    )

    if gaps:
        print(
            "min gap between requests to same host, "
            "ALL processes merged: "
            f"{min(gaps):.2f}s "
            "(must be >= 1.0)"
        )

    print(
        f"redis: {final}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--procs",
        type=int,
        default=4,
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

    asyncio.run(
        main(ap.parse_args())
    )