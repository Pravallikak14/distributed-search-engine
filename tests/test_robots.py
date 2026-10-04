import asyncio

from crawler.robots import RobotsCache, RobotsRules, parse_robots

ROBOTS = """
User-agent: *
Disallow: /private/
Disallow: /*.pdf$
Allow: /private/public/
Crawl-delay: 2

User-agent: MySearchBot
Disallow: /secret/
"""


def allowed(text, path, agent="MySearchBot"):
    return parse_robots(text, agent).is_allowed(path)


def test_specific_group_replaces_star_group():
    assert not allowed(ROBOTS, "/secret/x")
    assert allowed(ROBOTS, "/private/x")        # * rules apply avvavu
    assert parse_robots(ROBOTS, "MySearchBot").crawl_delay is None


def test_star_group_for_other_bots():
    assert not allowed(ROBOTS, "/private/x", agent="OtherBot")
    assert allowed(ROBOTS, "/secret/x", agent="OtherBot")
    assert parse_robots(ROBOTS, "OtherBot").crawl_delay == 2.0


def test_longest_match_wins():
    assert allowed(ROBOTS, "/private/public/doc", agent="OtherBot")
    assert not allowed(ROBOTS, "/private/other", agent="OtherBot")


def test_wildcard_and_end_anchor():
    assert not allowed(ROBOTS, "/a/b.pdf", agent="OtherBot")
    assert allowed(ROBOTS, "/a/b.pdf?x=1", agent="OtherBot")
    assert allowed(ROBOTS, "/a/b.pdfx", agent="OtherBot")


def test_tie_goes_to_allow():
    assert allowed("User-agent: *\nDisallow: /page\nAllow: /page", "/page")


def test_empty_disallow_allows_all():
    assert allowed("User-agent: *\nDisallow:", "/anything")


def test_disallow_root():
    assert not allowed("User-agent: *\nDisallow: /", "/x")


def test_multiple_user_agent_lines_share_rules():
    text = "User-agent: a\nUser-agent: MySearchBot\nDisallow: /x"
    assert not allowed(text, "/x")


def test_case_comments_bom():
    text = "\ufeffUSER-AGENT: *  # everyone\nDISALLOW: /a # comment"
    assert not allowed(text, "/a")
    assert allowed(text, "/b")


def test_garbage_does_not_crash():
    assert allowed("", "/x")
    assert allowed("<html>404 not found</html>", "/x")
    assert allowed("Disallow: /x", "/x")  # group lekunda rule: ignore
    assert parse_robots("User-agent: *\nCrawl-delay: abc", "x").crawl_delay is None


# ---------- RobotsCache ----------

def make_fetch(responses, calls):
    async def fetch(url):
        calls.append(url)
        await asyncio.sleep(0)
        r = responses[url]
        if isinstance(r, Exception):
            raise r
        return r
    return fetch


def test_status_handling():
    calls = []
    responses = {
        "https://ok.com/robots.txt": (200, "User-agent: *\nDisallow: /no"),
        "https://missing.com/robots.txt": (404, "not found"),
        "https://down.com/robots.txt": (503, ""),
        "https://slow.com/robots.txt": (None, None),
        "https://boom.com/robots.txt": RuntimeError("bad charset"),
    }
    cache = RobotsCache(make_fetch(responses, calls))

    async def run():
        return [
            await cache.is_allowed("https://ok.com/no"),
            await cache.is_allowed("https://ok.com/yes"),
            await cache.is_allowed("https://missing.com/no"),
            await cache.is_allowed("https://down.com/yes"),
            await cache.is_allowed("https://slow.com/yes"),
            await cache.is_allowed("https://boom.com/yes"),
        ]

    assert asyncio.run(run()) == [False, True, True, False, False, False]


def test_single_fetch_per_origin_under_concurrency():
    calls = []
    responses = {"https://a.com/robots.txt": (200, "User-agent: *\nDisallow:")}
    cache = RobotsCache(make_fetch(responses, calls))

    async def run():
        return await asyncio.gather(
            *(cache.is_allowed(f"https://a.com/p{i}") for i in range(20)))

    assert all(asyncio.run(run()))
    assert len(calls) == 1


def test_scheme_and_port_are_separate_origins():
    calls = []
    ok = (200, "")
    responses = {
        "http://a.com/robots.txt": ok,
        "https://a.com/robots.txt": ok,
        "https://a.com:8443/robots.txt": ok,
    }
    cache = RobotsCache(make_fetch(responses, calls))

    async def run():
        for u in ("http://a.com/x", "https://a.com/x", "https://a.com:8443/x",
                  "https://a.com/y"):
            await cache.is_allowed(u)

    asyncio.run(run())
    assert len(calls) == 3


def test_failure_ttl_retries_later():
    t = [0.0]
    calls = []
    responses = {"https://a.com/robots.txt": (503, "")}
    cache = RobotsCache(make_fetch(responses, calls), clock=lambda: t[0])

    async def run():
        assert not await cache.is_allowed("https://a.com/x")
        assert not await cache.is_allowed("https://a.com/x")   # cached
        assert len(calls) == 1
        t[0] += 301                                            # TTL expired
        responses["https://a.com/robots.txt"] = (200, "")
        assert await cache.is_allowed("https://a.com/x")
        assert len(calls) == 2

    asyncio.run(run())


def test_crawl_delay_exposed():
    calls = []
    responses = {"https://a.com/robots.txt": (200, "User-agent: *\nCrawl-delay: 5")}
    cache = RobotsCache(make_fetch(responses, calls))
    assert asyncio.run(cache.crawl_delay("https://a.com/x")) == 5.0