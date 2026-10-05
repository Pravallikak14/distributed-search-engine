import asyncio
from collections import defaultdict

from crawler.parser import parse_html
from crawler.url_utils import host_of, normalize_url


class CrawlStats:
    def __init__(self):
        self.pages = 0
        self.errors = 0
        self.blocked = 0
        self.starts = defaultdict(list)


async def worker(
    frontier,
    fetcher,
    robots,
    stats: CrawlStats,
    max_pages: int,
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

            # Get and store Crawl-delay
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

            if result.body is None:
                stats.errors += 1
                continue

            # Redirect may point to another host.
            # Check robots.txt for the final host too.
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

            # Stop after reaching page limit
            if stats.pages >= max_pages:
                frontier.stop()

            # Add discovered links
            for link in page.links:
                frontier.add(
                    link,
                    depth + 1,
                )

        finally:
            # VERY IMPORTANT:
            # Always release the host.
            frontier.done(
                url,
                elapsed,
            )
from collections import defaultdict

from crawler.parser import parse_html
from crawler.url_utils import host_of, normalize_url


class CrawlStats:
    def __init__(self):
        self.pages = 0
        self.errors = 0
        self.blocked = 0
        self.starts = defaultdict(list)


async def worker(
    frontier,
    fetcher,
    robots,
    stats: CrawlStats,
    max_pages: int,
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

            # Get and store Crawl-delay
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

            if result.body is None:
                stats.errors += 1
                continue

            # Redirect may point to another host.
            # Check robots.txt for the final host too.
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

            # Stop after reaching page limit
            if stats.pages >= max_pages:
                frontier.stop()

            # Add discovered links
            for link in page.links:
                frontier.add(
                    link,
                    depth + 1,
                )

        finally:
            # VERY IMPORTANT:
            # Always release the host.
            frontier.done(
                url,
                elapsed,
            )