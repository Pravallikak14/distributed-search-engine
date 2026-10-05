import asyncio

import pytest

from crawler.frontier import Frontier


def make(**kw):
    t = [0.0]
    return Frontier(clock=lambda: t[0], **kw), t


def test_dedupe_after_normalization():
    f, _ = make()

    assert f.add(
        "http://EXAMPLE.com:80/a?b=1&c=2#top"
    )

    assert not f.add(
        "http://example.com/a?c=2&b=1"
    )

    assert not f.add(
        "ftp://example.com/x"
    )


def test_same_host_serialized_and_delayed():
    f, t = make(min_delay=1.0)

    f.add("http://a.com/1")
    f.add("http://a.com/2")

    assert f.poll() == (
        ("http://a.com/1", 0),
        0.0,
    )

    # Same host is busy
    assert f.poll() == (None, None)

    f.done("http://a.com/1")

    # Host must cool down
    assert f.poll() == (None, 1.0)

    t[0] = 0.4

    item, wait = f.poll()

    assert item is None
    assert wait == pytest.approx(0.6)

    t[0] = 1.0

    assert f.poll()[0] == (
        "http://a.com/2",
        0,
    )


def test_slow_host_does_not_block_other_hosts():
    f, _ = make()

    f.add("http://slow.com/1")
    f.add("http://slow.com/2")
    f.add("http://fast.com/1")

    assert f.poll()[0][0] == "http://slow.com/1"

    # slow.com is busy, but fast.com can continue
    assert f.poll()[0][0] == "http://fast.com/1"

    assert f.poll() == (None, None)


def test_robots_crawl_delay_used():
    f, _ = make(min_delay=1.0)

    f.add("http://a.com/1")
    f.add("http://a.com/2")

    f.poll()

    f.set_crawl_delay(
        "http://a.com/1",
        5,
    )

    f.done("http://a.com/1")

    assert f.poll() == (None, 5.0)


def test_huge_crawl_delay_blocks_host():
    f, _ = make(max_delay=30)

    f.add("http://a.com/1")
    f.add("http://a.com/2")
    f.add("http://b.com/1")

    f.poll()

    f.set_crawl_delay(
        "http://a.com/1",
        3600,
    )

    f.done("http://a.com/1")

    assert not f.add(
        "http://a.com/3"
    )

    assert f.poll()[0] == (
        "http://b.com/1",
        0,
    )

    f.done("http://b.com/1")

    assert f.finished


def test_slow_responses_increase_delay_with_cap():
    f, _ = make(
        min_delay=1.0,
        max_delay=30.0,
    )

    f.add("http://a.com/1")
    f.add("http://a.com/2")

    f.poll()

    # 2 × 3 seconds = 6 seconds
    f.done(
        "http://a.com/1",
        elapsed=3.0,
    )

    assert f.poll() == (None, 6.0)

    # Maximum delay is capped
    g, _ = make(max_delay=10.0)

    g.add("http://a.com/1")
    g.add("http://a.com/2")

    g.poll()

    g.done(
        "http://a.com/1",
        elapsed=100,
    )

    assert g.poll() == (None, 10.0)


def test_depth_limit():
    f, _ = make(max_depth=2)

    assert f.add(
        "http://a.com/1",
        depth=2,
    )

    assert not f.add(
        "http://a.com/2",
        depth=3,
    )


def test_per_host_cap():
    f, _ = make(max_per_host=3)

    results = [
        f.add(f"http://a.com/{i}")
        for i in range(5)
    ]

    assert results == [
        True,
        True,
        True,
        False,
        False,
    ]

    assert f.add(
        "http://b.com/1"
    )


def test_finished_only_when_queue_empty_and_nothing_in_flight():
    f, _ = make()

    assert f.finished

    f.add("http://a.com/1")

    assert not f.finished

    f.poll()

    # Still in flight
    assert not f.finished

    f.done("http://a.com/1")

    assert f.finished


# ---------- async ----------

def test_async_get_waits_politely_and_terminates():

    async def run():
        f = Frontier(min_delay=0.1)

        f.add("http://a.com/1")
        f.add("http://a.com/2")

        loop = asyncio.get_running_loop()

        times = []

        async def w():
            while (
                item := await f.get()
            ) is not None:

                times.append(
                    loop.time()
                )

                await asyncio.sleep(0.01)

                f.done(item[0])

        await asyncio.wait_for(
            asyncio.gather(
                w(),
                w(),
                w(),
            ),
            timeout=5,
        )

        return times

    times = asyncio.run(run())

    assert len(times) == 2

    assert (
        times[1] - times[0] >= 0.1
    )


def test_get_wakes_when_new_host_added():

    async def run():
        f = Frontier()

        f.add(
            "http://a.com/1"
        )

        first = await f.get()

        waiter = asyncio.create_task(
            f.get()
        )

        await asyncio.sleep(0.05)

        assert not waiter.done()

        # Adding another host should wake
        # the waiting worker.
        f.add(
            "http://b.com/1"
        )

        got = await asyncio.wait_for(
            waiter,
            1,
        )

        f.done(first[0])
        f.done(got[0])

        return got

    assert asyncio.run(run())[0] == (
        "http://b.com/1"
    )


def test_stop_makes_get_return_none():

    async def run():
        f = Frontier()

        f.add(
            "http://a.com/1"
        )

        f.stop()

        return await f.get()

    assert asyncio.run(run()) is None