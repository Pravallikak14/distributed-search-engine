# Distributed Search Engine - Design

## 1. Goals

The system should:

- Crawl 400,000+ pages.
- Support a target query latency of p95 < 100 ms.
- Continue crawling safely when a worker crashes without losing URLs.
- Support multiple crawler workers and multiple index shards.
- Keep the crawler, indexer, ranker, and query API independently scalable.

## 2. Non-goals

This version will not focus on:

- JavaScript/browser rendering.
- Crawling the entire web at full internet scale.
- ML-based ranking.
- Image, video, or other non-HTML search.
- Complex distributed consensus systems.

## 3. Components

### Frontier

The frontier stores URLs that still need to be crawled and controls which URLs are assigned to workers.

Redis is used for fast queue operations. URLs should be acknowledged only after successful processing so that a worker crash does not silently lose work.

### Fetcher

The fetcher downloads web pages using HTTP. It handles timeouts, retries, response status codes, and basic request limits.

### Parser

The parser extracts useful information from downloaded HTML, including:

- Page title
- Text content
- Links
- Canonical URL
- Basic metadata

### Dedupe

The dedupe component prevents the crawler from processing the same URL repeatedly.

A combination of normalized URLs and a fast membership structure can be used to reduce duplicate work.

### Storage

PostgreSQL stores durable crawler metadata such as URLs, crawl state, status, timestamps, and other metadata that should survive service restarts.

### Indexer

The indexer converts parsed documents into an inverted index. The first version can use a simple term-to-document mapping and later add BM25 scoring.

### Ranker

The ranker calculates the relevance of matching documents. BM25 will be the initial ranking algorithm, with PageRank considered as a later improvement.

### Query API

The Query API accepts search requests, sends them to the query router, retrieves matching documents from index shards, ranks the results, and returns the top results.

## 4. Architecture

The high-level flow is:

Workers -> Redis Frontier -> Fetcher -> Parser -> Dedupe -> PostgreSQL

Parsed documents -> Indexer -> Index Shards

User Query -> Query Router -> Index Shards -> Ranker -> Results

Multiple crawler workers share the Redis frontier. Indexing is separated from crawling so both systems can scale independently.

## 5. Key Decisions and Alternatives

### Why Redis for the frontier instead of Kafka?

Redis is simple and fast for a first version of a URL frontier. It provides low-latency queue operations and is easy to run locally with Docker.

Kafka is designed for large-scale durable event streaming and would be useful when the system needs very high event throughput, replay, partitions, and multiple independent consumers.

For this project, Redis keeps the initial system simpler while still allowing us to demonstrate distributed workers.

### Why PostgreSQL?

PostgreSQL provides durable storage, transactions, indexing, and useful query capabilities.

Crawler state such as URL status, timestamps, retry counts, and metadata should survive process or container restarts.

A document database could also work, but PostgreSQL gives a strong relational model for crawler metadata and is easy to run locally.

### Why Python?

Python is productive for web crawling because libraries such as aiohttp and BeautifulSoup make HTTP fetching and HTML parsing straightforward.

Python also has strong support for async programming, testing, APIs, and data processing.

For a production system with extremely high CPU-bound throughput, other languages could be considered for specific components, but Python is a good choice for the first implementation.

## 6. Reliability

A worker should not permanently remove a URL from the frontier before the URL has been safely processed.

The frontier should support acknowledgement and recovery of pending work.

If a worker crashes while processing a URL, another worker should be able to reclaim the pending URL.

PostgreSQL stores durable crawl state so the system can recover after service restarts.

## 7. Open Questions

### How should politeness be enforced?

The crawler should maintain per-domain rate limits so that one domain is not overloaded.

Possible approaches include:

- Per-domain queues
- Redis-based rate-limit keys
- Last-request timestamps
- robots.txt support

### Bloom filter vs Redis Set for deduplication?

A Bloom filter is memory efficient and fast but can produce false positives.

A Redis Set provides exact membership checks but consumes more memory.

A possible design is to use a Bloom filter as a fast first check and Redis/PostgreSQL for authoritative deduplication.

## 8. Initial Performance Targets

| Metric | Target |
|---|---|
| Crawl throughput | 400,000+ pages |
| Query latency | p95 < 100 ms |
| Worker recovery | No silently lost URLs |
| Ranking | BM25 initially |
| Initial deployment | Docker Compose |

## 9. Future Improvements

Possible future improvements include:

- PageRank
- More advanced sharding
- Better retry scheduling
- robots.txt and crawl-delay support
- Bloom-filter based deduplication
- Distributed query routing
- Metrics and tracing
- Kubernetes deployment
## Fetcher

The fetcher downloads web pages asynchronously so multiple URLs can be processed at the same time.

### Concurrency

A global semaphore limits the number of active requests to 50.

This prevents too many connections from being opened at once and protects the crawler from resource exhaustion.

### Retries

The fetcher retries temporary failures such as:

- Network errors
- Timeouts
- HTTP 429
- HTTP 5xx

Permanent errors such as HTTP 404 are not retried.

### Exponential Backoff and Jitter

Retries use exponential backoff:

1 second, 2 seconds, 4 seconds, ...

A small random jitter is added to each delay.

Jitter prevents multiple workers from retrying at exactly the same time and sending another burst of requests to the same server.

### Size and Content-Type Limits

Only HTML responses are processed.

The fetcher limits the response body to 2 MB. PDFs, images, and other non-HTML content are skipped.

### Failure Handling

A failed URL returns a FetchResult containing the error instead of crashing the worker.

This allows the crawler to continue processing other URLs.
## Parser

The parser uses lxml because it is fast and suitable for processing a large
number of HTML pages.

It extracts the page title, clean text, and absolute HTTP/HTTPS links.

Scripts, styles, noscript, template, SVG, head content, and comments are
removed so they do not pollute the searchable text.

Relative URLs are converted to absolute URLs using the page URL and any
<base href> tag.

mailto, javascript, tel, fragment-only links, and nofollow links are skipped.
Duplicate links are removed while preserving their original order.

Malformed or empty HTML should never crash the crawler. The parser returns an
empty ParsedPage when parsing fails.
## URL Normalization

The crawler normalizes URLs before adding them to the frontier to reduce duplicate crawling.

Normalization rules:

- HTTP and HTTPS schemes are normalized to lowercase.
- Hostnames are normalized to lowercase.
- Default ports are removed (`:80` for HTTP and `:443` for HTTPS).
- Non-default ports are preserved.
- Userinfo is removed.
- Trailing dots in hostnames are removed.
- International domain names are converted to punycode.
- URL fragments are removed.
- Empty paths become `/`.
- Dot segments such as `.` and `..` are resolved.
- Path case is preserved.
- Trailing slashes are preserved, so `/a` and `/a/` remain distinct.
- Tracking parameters such as `utm_*`, `gclid`, `fbclid`, and similar parameters are removed.
- Query parameters are sorted while blank values are preserved.
- Percent encoding is normalized.
- Only HTTP and HTTPS URLs are accepted.
- URLs longer than 2048 characters are rejected.
- Normalization is idempotent, meaning normalizing an already normalized URL produces the same result.

The normalized URL is used for frontier deduplication and prevents the crawler from visiting the same logical URL multiple times due to tracking parameters, fragments, or different URL representations.

Known limitation: `/a` and `/a/` are intentionally kept separate because some servers treat them as different resources. Content-level deduplication can be added later.
## robots.txt

The crawler respects robots.txt before fetching pages from an origin.

### Rule handling

- A bot-specific `MySearchBot` group is preferred when present.
- Otherwise the `*` group is used.
- Rules support `*` wildcards and `$` end anchors.
- The longest matching rule wins.
- If matching rules have equal length, `Allow` wins.
- If no rule matches, the URL is allowed.
- `Crawl-delay` is parsed and stored for later politeness enforcement.

### Fetch status handling

| robots.txt result | Behavior | TTL |
|---|---|---:|
| 2xx | Parse robots.txt rules | 24 hours |
| 4xx except 429 | Treat as no robots.txt; allow | 24 hours |
| 429 | Temporarily disallow all | 5 minutes |
| 5xx | Temporarily disallow all | 5 minutes |
| Network error / timeout | Temporarily disallow all | 5 minutes |

### Cache and concurrency

Robots rules are cached per origin using:

`scheme://host:port`

Successful responses use a 24-hour TTL. Failure responses use a 5-minute TTL.

Multiple crawler workers requesting robots.txt for the same origin share one in-flight fetch, preventing a thundering-herd of requests.

The crawler uses its own robots.txt parser instead of Python's `urllib.robotparser` because the custom parser supports wildcard and end-anchor rules and implements longest-match precedence.

Crawl-delay is stored by the robots layer and will be enforced by the crawler's politeness mechanism in a later stage.
## Frontier & Politeness

The crawler uses an in-memory URL frontier that provides URL deduplication,
per-host queues, per-host concurrency control, adaptive rate limiting, and
spider-trap protection.

### Frontier design

URLs are normalized before being added to the frontier. A normalized URL is
stored in a global `seen` set so equivalent URLs are not crawled twice.

Each host has its own FIFO queue. A host can have at most one request in
flight at a time.

The frontier maintains a ready-at min-heap:

- Heap key = next allowed fetch time for a host.
- Idle hosts with queued work are represented in the heap.
- Busy hosts are not available for another fetch.
- Workers take the earliest ready host.
- If the earliest host is still cooling down, the worker waits only until
  that host becomes ready.
- Other hosts can continue while a slow host is busy.

This prevents one slow server from occupying all global worker slots.

### Adaptive politeness

After every completed fetch, the next request delay for that host is:

    delay = max(min_delay, robots_crawl_delay, 2 * last_fetch_time)

The delay is capped at 30 seconds.

For example, if a request takes 3 seconds, the adaptive delay becomes
6 seconds. This makes slow servers naturally receive fewer requests.

A robots.txt Crawl-delay greater than 30 seconds blocks the host. Queued
URLs for that host are dropped and future URLs for the host are rejected.

### Spider-trap defenses

The frontier limits crawler expansion using:

- Maximum crawl depth: 5
- Maximum URLs per host: 10,000
- Maximum URL length: 2,048 characters
- URL normalization and deduplication

These limits help prevent infinite calendar pages, generated URLs, and other
crawler traps from consuming the entire crawl budget.

### Termination

The frontier reports completion only when both conditions are true:

- No URLs remain queued.
- No worker currently has a URL in flight.

This is important because a worker may discover and add new URLs while another
worker is still processing a page.

### Worker reliability

Every URL obtained from the frontier is released through:

    finally:
        frontier.done(url, elapsed)

This ensures that an exception during fetching, robots checking, or parsing
does not permanently leave a host marked as busy.

### Day 6 benchmark

The crawl benchmark uses multiple seed domains and 30 workers.

Observed benchmark:

- Pages crawled: 301
- Errors: 1
- Robots blocked: 90
- Hosts touched: 77
- Throughput: 5.8 pages/s
- Minimum gap between requests to the same host: 1.02 seconds

The measured minimum gap is above the configured 1-second minimum, confirming
that the per-host politeness constraint is enforced.

The benchmark also demonstrates that throughput increases when more hosts are
available because each host can make progress independently while maintaining
the one-request-per-host constraint.