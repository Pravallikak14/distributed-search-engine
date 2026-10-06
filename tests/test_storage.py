import sqlite3

from crawler.parser import ParsedPage
from crawler.storage import PageStore


H = b"h" * 16


def page(text="hello world", title="T"):
    return ParsedPage(
        title=title,
        text=text,
        links=[],
    )


def test_roundtrip(tmp_path):
    s = PageStore(tmp_path / "p.db")

    text = "hello world " * 100

    s.add(
        "http://a.com/",
        "http://a.com/",
        1,
        page(text),
        ["http://a.com/x", "http://a.com/y"],
        H,
    )

    row = s.get("http://a.com/")

    assert row["title"] == "T"
    assert row["text"] == text
    assert row["links"] == [
        "http://a.com/x",
        "http://a.com/y",
    ]
    assert row["depth"] == 1

    assert s.get("http://missing.com/") is None

    s.close()


def test_duplicate_url_ignored_and_empty_links(tmp_path):
    s = PageStore(tmp_path / "p.db")

    s.add(
        "http://a.com/",
        "http://a.com/",
        0,
        page(),
        [],
        H,
    )

    s.add(
        "http://a.com/",
        "http://a.com/",
        0,
        page("different"),
        [],
        H,
    )

    assert s.count() == 1
    assert s.get("http://a.com/")["links"] == []

    s.close()


def test_batch_autoflush(tmp_path):
    path = tmp_path / "p.db"

    s = PageStore(path, batch_size=10)

    for i in range(10):
        s.add(
            f"http://a.com/{i}",
            "",
            0,
            page(f"t{i}"),
            [],
            H,
        )

    other = sqlite3.connect(path)

    assert (
        other.execute(
            "SELECT COUNT(*) FROM pages"
        ).fetchone()[0]
        == 10
    )

    other.close()
    s.close()


def test_compression_saves_space(tmp_path):
    s = PageStore(tmp_path / "p.db")

    s.add(
        "http://a.com/",
        "",
        0,
        page("lorem ipsum " * 1000),
        ["http://a.com/x"] * 50,
        H,
    )

    assert s.stored_bytes < s.raw_bytes / 5

    s.close()