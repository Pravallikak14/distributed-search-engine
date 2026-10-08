import asyncio
import uuid

import pytest
import redis
import redis.asyncio as aioredis

from crawler.redis_frontier import RedisFrontier
from crawler.url_utils import host_of


def _redis_up() -> bool:
    try:
        redis.Redis().ping()
        return True
    except redis.exceptions.RedisError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_up(),
    reason="redis not running",
)


def run(test, **kw):
    """Fresh key prefix + fresh event loop per test."""
    async def inner():
        r = aioredis.Redis(decode_responses=True)

        prefix = f"test:{uuid.uuid4().hex}:"

        f = RedisFrontier(
            r,
            prefix=prefix,
            bloom_capacity=10_000,
            **kw,
        )

        await f.connect()

        try:
            await test(f, r, prefix)
        finally:
            await f.reset()
            await r.aclose()

    asyncio.run(inner())


def test_dedupe_after_normalization():
    async def t(f, r, p):
        assert await f.add(
            "http://EXAMPLE.com:80/a?b=1&c=2#top"
        )

        assert not await f.add(
            "http://example.com/a?c=2&b=1"
        )

        assert not await f.add(
            "ftp://example.com/x"
        )

    run(t)


def test_dedupe_shared_between_instances():
    async def t(f, r, p):
        g = RedisFrontier(
            r,
            prefix=p,
            bloom_capacity=10_000,
        )

        await g.connect()

        assert await f.add(
            "http://a.com/1"
        )

        assert not await g.add(
            "http://a.com/1"
        )

    run(t)


def test_bloom_params_mismatch_rejected():
    async def t(f, r, p):
        g = RedisFrontier(
            r,
            prefix=p,
            bloom_capacity=999_999,
        )

        with pytest.raises(RuntimeError):
            await g.connect()

    run(t)


def test_same_host_serialized_and_delayed():
    async def t(f, r, p):
        await f.add("http://a.com/1")
        await f.add("http://a.com/2")

        assert (
            await f.poll()
        )[0] == ("http://a.com/1", 0)

        assert await f.poll() == (
            None,
            None,
        )

        await f.done("http://a.com/1")

        item, wait = await f.poll()

        assert (
            item is None
            and 0 < wait <= 0.3
        )

        await asyncio.sleep(0.35)

        assert (
            await f.poll()
        )[0] == ("http://a.com/2", 0)

    run(t, min_delay=0.3)


def test_slow_host_does_not_block_other_hosts():
    async def t(f, r, p):
        await f.add("http://slow.com/1")
        await f.add("http://slow.com/2")
        await f.add("http://fast.com/1")

        got = {
            (await f.poll())[0][0]
            for _ in range(2)
        }

        assert got == {
            "http://slow.com/1",
            "http://fast.com/1",
        }

        assert await f.poll() == (
            None,
            None,
        )

    run(t)


def test_robots_crawl_delay_used():
    async def t(f, r, p):
        await f.add("http://a.com/1")
        await f.add("http://a.com/2")

        await f.poll()

        await f.set_crawl_delay(
            "http://a.com/1",
            2.0,
        )

        await f.done(
            "http://a.com/1"
        )

        item, wait = await f.poll()

        assert (
            item is None
            and 1.5 < wait <= 2.0
        )

    run(t, min_delay=0.1)


def test_huge_crawl_delay_blocks_host():
    async def t(f, r, p):
        await f.add("http://a.com/1")
        await f.add("http://a.com/2")

        assert (
            await f.poll()
        )[0] == ("http://a.com/1", 0)

        await f.add("http://b.com/1")

        await f.set_crawl_delay(
            "http://a.com/1",
            3600,
        )

        await f.done(
            "http://a.com/1"
        )

        assert not await f.add(
            "http://a.com/3"
        )

        assert (
            await f.poll()
        )[0] == ("http://b.com/1", 0)

        await f.done(
            "http://b.com/1"
        )

        assert await f.finished()

    run(t, max_delay=30)


def test_slow_responses_increase_delay_with_cap():
    async def t(f, r, p):
        await f.add("http://a.com/1")
        await f.add("http://a.com/2")

        await f.poll()

        await f.done(
            "http://a.com/1",
            elapsed=3.0,
        )

        item, wait = await f.poll()

        assert (
            item is None
            and 5.5 < wait <= 6.0
        )

    run(t, min_delay=0.1)

    async def capped(f, r, p):
        await f.add("http://a.com/1")
        await f.add("http://a.com/2")

        await f.poll()

        await f.done(
            "http://a.com/1",
            elapsed=100,
        )

        item, wait = await f.poll()

        assert (
            item is None
            and 1.5 < wait <= 2.0
        )

    run(
        capped,
        min_delay=0.1,
        max_delay=2.0,
    )


def test_depth_limit_and_per_host_cap():
    async def t(f, r, p):
        assert await f.add(
            "http://a.com/1",
            depth=2,
        )

        assert not await f.add(
            "http://a.com/2",
            depth=3,
        )

        results = [
            await f.add(
                f"http://b.com/{i}"
            )
            for i in range(5)
        ]

        assert results == [
            True,
            True,
            True,
            False,
            False,
        ]

        assert await f.add(
            "http://c.com/1"
        )

    run(
        t,
        max_depth=2,
        max_per_host=3,
    )


def test_finished_only_when_queue_empty_and_nothing_in_flight():
    async def t(f, r, p):
        assert await f.finished()

        await f.add(
            "http://a.com/1"
        )

        assert not await f.finished()

        await f.poll()

        assert not await f.finished()

        await f.done(
            "http://a.com/1"
        )

        assert await f.finished()

    run(t)


def test_stop_makes_get_return_none():
    async def t(f, r, p):
        await f.add(
            "http://a.com/1"
        )

        await f.stop()

        assert await f.get() is None

    run(t)


def test_two_processes_each_url_exactly_once_and_hosts_serialized():
    async def t(f, r, p):
        g = RedisFrontier(
            r,
            prefix=p,
            bloom_capacity=10_000,
            min_delay=0.05,
        )

        await g.connect()

        urls = [
            f"http://h{i}.com/{j}"
            for i in range(10)
            for j in range(5)
        ]

        assert await f.add_many(urls) == 50

        got = []
        active = set()
        overlaps = []

        async def w(fr):
            while (
                item := await fr.get()
            ) is not None:

                host = host_of(item[0])

                if host in active:
                    overlaps.append(host)

                active.add(host)
                got.append(item[0])

                await asyncio.sleep(0.005)

                active.discard(host)

                await fr.done(
                    item[0]
                )

        await asyncio.wait_for(
            asyncio.gather(
                *(w(f) for _ in range(10)),
                *(w(g) for _ in range(10)),
            ),
            timeout=30,
        )

        assert sorted(got) == sorted(urls)

        assert overlaps == []

    run(t, min_delay=0.05)


def test_stats():
    async def t(f, r, p):
        await f.add_many(
            [
                f"http://a.com/{i}"
                for i in range(3)
            ]
        )

        s = await f.stats()

        assert s["queued"] == 3
        assert s["hosts"] == 1
        assert 2 <= s["seen~"] <= 4

    run(t)