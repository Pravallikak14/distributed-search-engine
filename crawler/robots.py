import asyncio
import math
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from crawler.fetcher import BOT_TOKEN


FetchText = Callable[
    [str],
    Awaitable[tuple[int | None, str | None]]
]

SUCCESS_TTL = 24 * 3600
FAILURE_TTL = 300


@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern


def _compile(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")

    if anchored:
        pattern = pattern[:-1]

    body = ".*".join(
        re.escape(part)
        for part in pattern.split("*")
    )

    return re.compile(
        body + ("$" if anchored else "")
    )


class RobotsRules:
    def __init__(
        self,
        rules=(),
        crawl_delay=None,
        disallow_all=False
    ):
        self.rules = list(rules)
        self.crawl_delay = crawl_delay
        self.disallow_all = disallow_all

    def is_allowed(self, path_and_query: str) -> bool:
        if self.disallow_all:
            return False

        best: Rule | None = None

        for rule in self.rules:
            if not rule.regex.match(path_and_query):
                continue

            if (
                best is None
                or len(rule.pattern) > len(best.pattern)
                or (
                    len(rule.pattern) == len(best.pattern)
                    and rule.allow
                    and not best.allow
                )
            ):
                best = rule

        return True if best is None else best.allow


def parse_robots(text: str, agent: str) -> RobotsRules:
    agent = agent.lower()

    groups: list[dict] = []
    current: dict | None = None
    last_was_agent = False

    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.split("#", 1)[0].strip()

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if current is None or not last_was_agent:
                current = {
                    "agents": set(),
                    "rules": [],
                    "delay": None,
                }
                groups.append(current)

            current["agents"].add(value.lower())
            last_was_agent = True

        elif key in ("allow", "disallow"):
            last_was_agent = False

            if current is not None and value:
                current["rules"].append(
                    Rule(
                        key == "allow",
                        value,
                        _compile(value)
                    )
                )

        elif key == "crawl-delay":
            last_was_agent = False

            if current is not None and current["delay"] is None:
                try:
                    delay = float(value)

                    if math.isfinite(delay) and delay >= 0:
                        current["delay"] = delay

                except ValueError:
                    pass

        # sitemap / unknown fields are ignored

    chosen = (
        [g for g in groups if agent in g["agents"]]
        or [g for g in groups if "*" in g["agents"]]
    )

    rules = [
        rule
        for group in chosen
        for rule in group["rules"]
    ]

    delay = next(
        (
            group["delay"]
            for group in chosen
            if group["delay"] is not None
        ),
        None,
    )

    return RobotsRules(rules, delay)


def _path_and_query(url: str) -> str:
    parts = urlsplit(url)

    return (
        parts.path or "/"
    ) + (
        f"?{parts.query}"
        if parts.query
        else ""
    )


class RobotsCache:
    def __init__(
        self,
        fetch_text: FetchText,
        token: str = BOT_TOKEN,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._fetch = fetch_text
        self._token = token
        self._clock = clock

        self._cache: dict[
            str,
            tuple[float, RobotsRules]
        ] = {}

        self._inflight: dict[
            str,
            asyncio.Task
        ] = {}

    async def rules_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)

        origin = f"{parts.scheme}://{parts.netloc}"

        # Check cache
        hit = self._cache.get(origin)

        if hit and hit[0] > self._clock():
            return hit[1]

        # Share an in-flight request
        task = self._inflight.get(origin)

        if task is None:
            task = asyncio.ensure_future(
                self._load(origin)
            )

            self._inflight[origin] = task

            task.add_done_callback(
                lambda _task:
                self._inflight.pop(origin, None)
            )

        # One caller cancelling should not
        # cancel the shared request.
        return await asyncio.shield(task)

    async def _load(self, origin: str) -> RobotsRules:
        try:
            status, text = await self._fetch(
                origin + "/robots.txt"
            )

        except Exception:
            status, text = None, None

        # 2xx -> parse robots.txt
        if (
            status is not None
            and 200 <= status < 300
            and text is not None
        ):
            rules = parse_robots(
                text,
                self._token
            )
            ttl = SUCCESS_TTL

        # 4xx except 429 -> no robots.txt
        elif (
            status is not None
            and 400 <= status < 500
            and status != 429
        ):
            rules = RobotsRules()
            ttl = SUCCESS_TTL

        # 5xx / 429 / network failure
        # -> temporarily disallow everything
        else:
            rules = RobotsRules(
                disallow_all=True
            )
            ttl = FAILURE_TTL

        self._cache[origin] = (
            self._clock() + ttl,
            rules,
        )

        return rules

    async def is_allowed(self, url: str) -> bool:
        rules = await self.rules_for(url)

        return rules.is_allowed(
            _path_and_query(url)
        )

    async def crawl_delay(
        self,
        url: str
    ) -> float | None:
        rules = await self.rules_for(url)

        return rules.crawl_delay