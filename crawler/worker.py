import asyncio
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
    loop = asyncio.get_running_loop()

    while True:
        item = await frontier.get()

        if item is None:
            return

        url, depth = item
        elapsed = 0.0

        try:
            # Check robots.txt before fetching
            if not await robots.is_allowed(url):
                stats.blocked += 1
                continue

            # Get robots Crawl-delay
            frontier.set_crawl_delay(
                url,
                await robots.crawl_delay(url),
            )

            # Record fetch start time
            stats.starts[host_of(url)].append(
                loop.time()
            )

            # Fetch page
            result = await fetcher.fetch(url)

            elapsed = result.elapsed

            stats.fetch_times.append(elapsed)

            # Day 7 bug fix:
            # Only successful 2xx responses count as pages.
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

                stats.error_kinds[error_kind] += 1

                continue

            # Cross-host redirect:
            # check robots.txt for target host too.
            final = result.final_url or url

            final_norm = normalize_url(final)

            if (
                final_norm
                and host_of(final_norm) != host_of(url)
                and not await robots.is_allowed(final_norm)
            ):
                stats.blocked += 1
                continue

            # Parse HTML
            page = parse_html(
                result.body,
                final,
            )

            stats.pages += 1

            if stats.pages >= max_pages:
                frontier.stop()

            # Content-level deduplication
            digest = content_hash(page.text)

            if (
                page.text
                and dedupe is not None
                and dedupe.is_duplicate(digest)
            ):
                stats.duplicates += 1

                # Do not store duplicate pages
                # and do not follow their links.
                continue

            # Normalize and deduplicate links
            links = list(
                dict.fromkeys(
                    normalized
                    for raw in page.links
                    if (
                        normalized := normalize_url(raw)
                    )
                )
            )

            # Store successfully crawled page
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

            # Add discovered links to frontier
            for link in links:
                frontier.add(
                    link,
                    depth + 1,
                )

        finally:
            # Always release the host.
            frontier.done(
                url,
                elapsed,
            )