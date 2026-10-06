import pytest

from crawler.bloom import BloomFilter
from crawler.frontier import Frontier


def test_no_false_negatives():
    bf = BloomFilter(5000, 0.01)

    items = [f"http://a.com/{i}" for i in range(5000)]

    for item in items:
        bf.add(item)

    assert all(item in bf for item in items)
    assert len(bf) <= 5000


def test_add_reports_newness():
    bf = BloomFilter(1000)

    assert bf.add("x") is True
    assert bf.add("x") is False
    assert len(bf) == 1


def test_false_positive_rate_near_target():
    bf = BloomFilter(10_000, 0.01)

    for i in range(10_000):
        bf.add(f"in-{i}")

    fp = sum(
        1
        for i in range(10_000)
        if f"out-{i}" in bf
    ) / 10_000

    assert fp < 0.02
    assert bf.estimated_fp_rate() == pytest.approx(0.01, rel=0.3)


def test_sizing_matches_math():
    bf = BloomFilter(10_000_000, 0.01)

    assert bf.num_hashes == 7
    assert 11_000_000 < bf.size_bytes < 13_000_000


@pytest.mark.parametrize(
    "cap, p",
    [
        (0, 0.01),
        (-5, 0.01),
        (100, 0),
        (100, 1),
    ],
)
def test_invalid_args(cap, p):
    with pytest.raises(ValueError):
        BloomFilter(cap, p)


def test_frontier_with_bloom_dedupes():
    f = Frontier(seen=BloomFilter(1000))

    assert f.add("http://EXAMPLE.com/a?b=1&c=2")
    assert not f.add("http://example.com/a?c=2&b=1")
    assert f.add("http://example.com/other")

    assert f.stats["seen"] == 2