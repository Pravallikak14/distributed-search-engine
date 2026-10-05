import asyncio
import heapq
import itertools
import time
from collections import defaultdict, deque
from typing import Callable

from crawler.url_utils import host_of, normalize_url


class Frontier:
    def __init__(
        self,
        min_delay: float = 1.0,
        max_delay: float = 30.0,
        max_depth: int = 5,
        max_per_host: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_depth = max_depth
        self.max_per_host = max_per_host
        self._clock = clock

        # host -> queue of (url, depth)
        self._queues: dict[str, deque] = defaultdict(deque)

        # (ready_at, sequence, host)
        self._heap: list[tuple[float, int, str]] = []

        self._seq = itertools.count()

        self._ready_at: dict[str, float] = {}

        # Hosts currently being fetched
        self._busy: set[str] = set()

        # robots.txt Crawl-delay per host
        self._robots_delay: dict[str, float] = {}

        # Hosts that should no longer be crawled
        self._blocked: set[str] = set()

        # Normalized URLs already seen
        self._seen: set[str] = set()

        # Number of URLs accepted for each host
        self._host_count: dict[str, int] = defaultdict(int)

        self._queued = 0
        self._in_flight = 0

        self._stopped = False

        # Wakes workers when frontier state changes
        self._changed = asyncio.Event()

    # ---------- producing ----------

    def add(self, url: str, depth: int = 0) -> bool:
        """Returns True if URL was accepted into the frontier."""

        norm = normalize_url(url)

        if (
            norm is None
            or depth > self.max_depth
            or norm in self._seen
        ):
            return False

        host = host_of(norm)

        if (
            host in self._blocked
            or self._host_count[host] >= self.max_per_host
        ):
            return False

        self._seen.add(norm)
        self._host_count[host] += 1

        queue = self._queues[host]
        was_empty = not queue

        queue.append((norm, depth))
        self._queued += 1

        if was_empty and host not in self._busy:
            self._push(host)

        self._changed.set()

        return True

    def _push(self, host: str) -> None:
        ready = self._ready_at.get(
            host,
            self._clock()
        )

        heapq.heappush(
            self._heap,
            (
                ready,
                next(self._seq),
                host,
            ),
        )

    # ---------- consuming ----------

    def poll(self):
        """
        Non-blocking.

        Returns:
            ((url, depth), 0) when a URL is ready.
            (None, wait_seconds) when a host is cooling down.
            (None, None) when nothing is currently available.
        """

        if self._stopped:
            return None, None

        now = self._clock()

        while self._heap:
            ready_at, _, host = self._heap[0]

            queue = self._queues.get(host)

            # Stale heap entry
            if not queue:
                heapq.heappop(self._heap)
                continue

            # Host still cooling down
            if ready_at > now:
                return None, ready_at - now

            heapq.heappop(self._heap)

            url, depth = queue.popleft()

            self._queued -= 1

            # One request per host at a time
            self._busy.add(host)

            self._in_flight += 1

            return (url, depth), 0.0

        return None, None

    async def get(self):
        """Wait until a URL is ready.

        Returns None when the crawl is finished.
        """

        while True:
            item, wait = self.poll()

            if item is not None:
                return item

            if self.finished:
                return None

            # No await between poll() and clear(),
            # so a wakeup cannot be lost.
            self._changed.clear()

            try:
                await asyncio.wait_for(
                    self._changed.wait(),
                    timeout=wait,
                )

            except asyncio.TimeoutError:
                pass

    def done(
        self,
        url: str,
        elapsed: float = 0.0,
    ) -> None:
        """
        Worker must call this in finally for every URL it gets.
        """

        host = host_of(url)

        if host not in self._busy:
            return

        self._busy.discard(host)

        self._in_flight -= 1

        # Adaptive politeness:
        # minimum delay
        # OR robots Crawl-delay
        # OR 2 x previous fetch duration
        delay = max(
            self.min_delay,
            self._robots_delay.get(host, 0.0),
            2 * elapsed,
        )

        # Never wait more than max_delay
        delay = min(
            delay,
            self.max_delay,
        )

        self._ready_at[host] = (
            self._clock() + delay
        )

        if self._queues.get(host):
            self._push(host)

        self._changed.set()

    def set_crawl_delay(
        self,
        url: str,
        delay: float | None,
    ) -> None:
        if delay is None:
            return

        host = host_of(url)

        # Crawl-delay larger than max_delay:
        # skip this host.
        if delay > self.max_delay:
            self._blocked.add(host)

            queue = self._queues.get(host)

            if queue:
                self._queued -= len(queue)
                queue.clear()

            self._changed.set()

        else:
            self._robots_delay[host] = delay

    def stop(self) -> None:
        self._stopped = True
        self._changed.set()

    @property
    def finished(self) -> bool:
        return (
            self._stopped
            or (
                self._queued == 0
                and self._in_flight == 0
            )
        )

    @property
    def stats(self) -> dict:
        return {
            "queued": self._queued,
            "in_flight": self._in_flight,
            "seen": len(self._seen),
            "hosts": len(self._host_count),
        }