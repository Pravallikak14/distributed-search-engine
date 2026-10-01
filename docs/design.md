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