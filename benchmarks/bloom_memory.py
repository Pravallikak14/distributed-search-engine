import tracemalloc

from crawler.bloom import BloomFilter


N = 1_000_000
PROBES = 200_000


def urls(start, n):
    return (
        f"http://example.com/page/{i}?id={i}"
        for i in range(start, start + n)
    )


# Measure normal Python set
tracemalloc.start()

s = set()

for u in urls(0, N):
    s.add(u)

set_mb = tracemalloc.get_traced_memory()[0] / 1e6

del s
tracemalloc.stop()


# Measure Bloom filter
tracemalloc.start()

bf = BloomFilter(N, 0.01)

for u in urls(0, N):
    bf.add(u)

bloom_mb = tracemalloc.get_traced_memory()[0] / 1e6

tracemalloc.stop()


# Measure false-positive rate
fp = sum(
    1
    for u in urls(N, PROBES)
    if u in bf
) / PROBES


print(
    f"{N:,} URLs: "
    f"set={set_mb:.0f} MB  "
    f"bloom={bloom_mb:.1f} MB  "
    f"({set_mb / bloom_mb:.0f}x smaller)"
)

print(
    f"measured false-positive rate: "
    f"{fp:.3%} "
    f"(target 1%), "
    f"k={bf.num_hashes}"
)