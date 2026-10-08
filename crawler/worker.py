import time
from collections import Counter, defaultdict

from crawler.dedupe import content_hash
from crawler.parser import parse_html
from crawler.url_utils import host_of, normalize_url


class CrawlStats:
    def __init__(self):
        self.pages = 0
        self.duplicates = 0
        self.errors = 0
        self.blocked = 0
        self.error_kinds = Counter()
        self.fetch_times: list[float] = []
        self.pages_per_host = Counter()
        self.starts = defaultdict(list)


async def worker(
    frontier,
    fetcher,
    robots,
    stats: CrawlStats,
    max_pages: int,
    store=None,
    dedupe=None,
):
    while True:
        item = await frontier.get()

        if item is None:
            return

        url, depth = item
        elapsed = 0.0

        try:
            if not await robots.is_allowed(url):
                stats.blocked += 1
                continue

            delay = await robots.crawl_delay(url)

            if delay is not None:
                await frontier.set_crawl_delay(
                    url,
                    delay,
                )

            stats.starts[
                host_of(url)
            ].append(time.time())

            result = await fetcher.fetch(url)

            elapsed = result.elapsed

            stats.fetch_times.append(
                elapsed
            )

            if (
                result.body is None
                or result.status is None
                or not 200 <= result.status < 300
            ):
                stats.errors += 1

                error_kind = (
                    result.error
                    or f"HTTP {result.status}"
                )

                stats.error_kinds[
                    error_kind
                ] += 1

                continue

            final = (
                result.final_url
                or url
            )

            final_norm = normalize_url(
                final
            )

            if (
                final_norm
                and host_of(final_norm)
                != host_of(url)
                and not await robots.is_allowed(
                    final_norm
                )
            ):
                stats.blocked += 1
                continue

            page = parse_html(
                result.body,
                final,
            )

            stats.pages += 1

            if (
                await frontier.count_page()
                >= max_pages
            ):
                await frontier.stop()

            digest = content_hash(
                page.text
            )

            if (
                page.text
                and dedupe is not None
                and dedupe.is_duplicate(digest)
            ):
                stats.duplicates += 1
                continue

            links = list(
                dict.fromkeys(
                    n
                    for raw in page.links
                    if (
                        n := normalize_url(raw)
                    )
                )
            )

            if store is not None:
                store.add(
                    url,
                    final_norm or final,
                    depth,
                    page,
                    links,
                    digest,
                )

            stats.pages_per_host[
                host_of(url)
            ] += 1

            await frontier.add_many(
                links,
                depth + 1,
            )

        finally:
            await frontier.done(
                url,
                elapsed,
            )