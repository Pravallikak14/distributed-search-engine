import asyncio
import math
import random

import redis.asyncio as aioredis
from redis.exceptions import NoScriptError

from crawler.bloom import bloom_params, bloom_positions
from crawler.url_utils import host_of, normalize_url


# ARGV: prefix, host, depth, url, max_per_host, *bloom_positions
ADD = """
local p, host = ARGV[1], ARGV[2]
if redis.call('SISMEMBER', p..'blocked', host) == 1 then return 0 end
local cnt = tonumber(redis.call('HGET', p..'hcount', host) or '0')
if cnt >= tonumber(ARGV[5]) then return 0 end

local fresh = 0
for i = 6, #ARGV do
  if redis.call('SETBIT', p..'bloom', ARGV[i], 1) == 0 then
    fresh = 1
  end
end

if fresh == 0 then return 0 end

redis.call('HINCRBY', p..'hcount', host, 1)

local len = redis.call(
  'RPUSH',
  p..'q:'..host,
  ARGV[3]..' '..ARGV[4]
)

redis.call('INCR', p..'queued')

if len == 1 and redis.call('HEXISTS', p..'busy', host) == 0 then
  local t = redis.call('TIME')
  local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
  local ra = tonumber(redis.call('HGET', p..'next', host) or '0')
  redis.call('ZADD', p..'ready', math.max(now, ra), host)
end

return 1
"""


# ARGV: prefix
# Returns {1,host,item} | {2,wait} | {0} nothing | {4} stopped
POLL = """
local p = ARGV[1]

if redis.call('EXISTS', p..'stopped') == 1 then
  return {4}
end

local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000

for _ = 1, 100 do
  local top = redis.call(
    'ZRANGE',
    p..'ready',
    0,
    0,
    'WITHSCORES'
  )

  if #top == 0 then
    return {0}
  end

  local host, score = top[1], tonumber(top[2])

  if score > now then
    return {2, tostring(score - now)}
  end

  redis.call('ZREM', p..'ready', host)

  local item = redis.call('LPOP', p..'q:'..host)

  if item then
    redis.call('DECR', p..'queued')
    redis.call('HSET', p..'busy', host, item)

    return {1, host, item}
  end
end

return {0}
"""


# ARGV: prefix, host, elapsed, min_delay, max_delay
DONE = """
local p, host = ARGV[1], ARGV[2]

if redis.call('HDEL', p..'busy', host) == 0 then
  return 0
end

local elapsed = tonumber(ARGV[3])
local min_d = tonumber(ARGV[4])
local max_d = tonumber(ARGV[5])

local rd = tonumber(
  redis.call('HGET', p..'rdelay', host) or '0'
)

local delay = math.min(
  math.max(min_d, rd, 2 * elapsed),
  max_d
)

local t = redis.call('TIME')

local ra =
  tonumber(t[1])
  + tonumber(t[2]) / 1000000
  + delay

redis.call(
  'HSET',
  p..'next',
  host,
  string.format('%.6f', ra)
)

if redis.call('LLEN', p..'q:'..host) > 0 then
  redis.call('ZADD', p..'ready', ra, host)
end

return 1
"""


# ARGV: prefix, host, delay, max_delay
SET_DELAY = """
local p, host, delay, max_d =
  ARGV[1],
  ARGV[2],
  tonumber(ARGV[3]),
  tonumber(ARGV[4])

if delay > max_d then

  redis.call('SADD', p..'blocked', host)

  local n = redis.call(
    'LLEN',
    p..'q:'..host
  )

  if n > 0 then
    redis.call('DEL', p..'q:'..host)
    redis.call('DECRBY', p..'queued', n)
  end

  redis.call('ZREM', p..'ready', host)

else

  redis.call(
    'HSET',
    p..'rdelay',
    host,
    ARGV[3]
  )

end

return 1
"""


SCRIPTS = {
    "add": ADD,
    "poll": POLL,
    "done": DONE,
    "set_delay": SET_DELAY,
}


class RedisFrontier:
    """
    Same behaviour as Frontier (Day 6), shared across processes via Redis.

    Note:
    Lua scripts build key names from the prefix, so this targets a
    single Redis instance (Cluster would need hash tags).
    """

    def __init__(
        self,
        r,
        prefix="fr:",
        min_delay=1.0,
        max_delay=30.0,
        max_depth=5,
        max_per_host=10_000,
        bloom_capacity=1_000_000,
        bloom_error=0.01,
        idle_poll=0.2,
    ):
        self._r = r
        self._p = prefix

        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_depth = max_depth
        self.max_per_host = max_per_host

        self._m, self._k = bloom_params(
            bloom_capacity,
            bloom_error,
        )

        self._idle_poll = idle_poll

        self._sha: dict[str, str] = {}

        self._changed = asyncio.Event()

    # ---------- setup ----------

    async def connect(self) -> None:
        params = f"{self._m},{self._k}"

        if not await self._r.set(
            self._p + "params",
            params,
            nx=True,
        ):
            existing = await self._r.get(
                self._p + "params"
            )

            if existing != params:
                raise RuntimeError(
                    f"Bloom params mismatch: "
                    f"redis has {existing}, "
                    f"this process {params}"
                )

        await self._load_scripts()

    async def _load_scripts(self) -> None:
        for name, src in SCRIPTS.items():
            self._sha[name] = await self._r.script_load(src)

    async def reset(self) -> None:
        keys = [
            k
            async for k in self._r.scan_iter(
                match=self._p + "*",
                count=1000,
            )
        ]

        if keys:
            await self._r.unlink(*keys)

    async def _pipe(
        self,
        name: str,
        arg_lists: list[list],
    ) -> list:

        for attempt in (0, 1):

            try:
                async with self._r.pipeline(
                    transaction=False
                ) as pipe:

                    for args in arg_lists:
                        pipe.evalsha(
                            self._sha[name],
                            0,
                            *args,
                        )

                    return await pipe.execute()

            except NoScriptError:
                # Redis restarted / SCRIPT FLUSH
                if attempt:
                    raise

                await self._load_scripts()

    async def _call(self, name: str, *args):
        return (
            await self._pipe(
                name,
                [list(args)],
            )
        )[0]

    # ---------- producing ----------

    async def add_many(
        self,
        urls,
        depth: int = 0,
    ) -> int:
        """
        Returns number of URLs accepted.
        One pipeline round-trip.
        """

        if depth > self.max_depth:
            return 0

        norms = list(
            dict.fromkeys(
                n
                for u in urls
                if (n := normalize_url(u))
            )
        )

        if not norms:
            return 0

        arg_lists = [
            [
                self._p,
                host_of(n),
                depth,
                n,
                self.max_per_host,
                *bloom_positions(
                    n,
                    self._m,
                    self._k,
                ),
            ]
            for n in norms
        ]

        results = await self._pipe(
            "add",
            arg_lists,
        )

        self._changed.set()

        return sum(int(x) for x in results)

    async def add(
        self,
        url: str,
        depth: int = 0,
    ) -> bool:
        return (
            await self.add_many(
                [url],
                depth,
            )
            == 1
        )

    # ---------- consuming ----------

    async def poll(self):
        """
        ((url, depth), 0.0)
        |
        (None, wait_seconds)
        |
        (None, None)
        """

        res = await self._call(
            "poll",
            self._p,
        )

        status = int(res[0])

        if status == 1:
            depth, url = res[2].split(
                " ",
                1,
            )

            return (
                (url, int(depth)),
                0.0,
            )

        if status == 2:
            return (
                None,
                float(res[1]),
            )

        return (
            None,
            None,
        )

    async def get(self):
        """
        Wait until a URL is ready.
        None when crawl finished.
        """

        while True:

            item, wait = await self.poll()

            if item is not None:
                return item

            if await self.finished():
                return None

            delay = (
                min(wait, 1.0)
                if wait is not None
                else self._idle_poll
            )

            delay += random.random() * 0.02

            # jitter: workers sync avvakunda
            self._changed.clear()

            try:
                await asyncio.wait_for(
                    self._changed.wait(),
                    timeout=delay,
                )
            except asyncio.TimeoutError:
                pass

    async def done(
        self,
        url: str,
        elapsed: float = 0.0,
    ) -> None:

        await self._call(
            "done",
            self._p,
            host_of(url),
            float(elapsed),
            self.min_delay,
            self.max_delay,
        )

        self._changed.set()

    async def set_crawl_delay(
        self,
        url: str,
        delay,
    ) -> None:

        if delay is None:
            return

        await self._call(
            "set_delay",
            self._p,
            host_of(url),
            float(delay),
            self.max_delay,
        )

    async def count_page(self) -> int:
        """
        Global fetched-pages counter
        (shared by all processes).
        """

        return int(
            await self._r.incr(
                self._p + "pages"
            )
        )

    async def stop(self) -> None:
        await self._r.set(
            self._p + "stopped",
            1,
        )

    async def finished(self) -> bool:
        async with self._r.pipeline(
            transaction=True
        ) as pipe:

            pipe.get(
                self._p + "queued"
            )

            pipe.hlen(
                self._p + "busy"
            )

            pipe.exists(
                self._p + "stopped"
            )

            queued, busy, stopped = (
                await pipe.execute()
            )

        return bool(stopped) or (
            int(queued or 0) == 0
            and busy == 0
        )

    async def stats(self) -> dict:
        p = self._p

        async with self._r.pipeline(
            transaction=True
        ) as pipe:

            pipe.get(
                p + "queued"
            )

            pipe.hlen(
                p + "busy"
            )

            pipe.zcard(
                p + "ready"
            )

            pipe.hlen(
                p + "hcount"
            )

            pipe.get(
                p + "pages"
            )

            pipe.bitcount(
                p + "bloom"
            )

            (
                queued,
                busy,
                ready,
                hosts,
                pages,
                bits,
            ) = await pipe.execute()

        frac = min(
            bits / self._m,
            0.999999,
        )

        seen_est = int(
            -(self._m / self._k)
            * math.log(1 - frac)
        )

        return {
            "queued": int(queued or 0),
            "in_flight": busy,
            "ready_hosts": ready,
            "hosts": hosts,
            "pages": int(pages or 0),
            "seen~": seen_est,
            "bloom_fp~": round(
                frac ** self._k,
                5,
            ),
        }