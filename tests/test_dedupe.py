from crawler.dedupe import ContentDedupe, content_hash


def test_hash_stable_and_distinct():
    assert content_hash("a") == content_hash("a")
    assert content_hash("a") != content_hash("b")
    assert len(content_hash("a")) == 16


def test_duplicate_detection():
    d = ContentDedupe()

    h = content_hash("same text")

    assert not d.is_duplicate(h)
    assert d.is_duplicate(h)
    assert not d.is_duplicate(content_hash("other"))
    assert len(d) == 2