from crawler.parser import ParsedPage, parse_html

BASE = "https://example.com/dir/page.html"


def test_title_and_text():
    html = """<html><head><title> My   Page </title></head>
    <body><p>Hello</p><p>World</p></body></html>"""
    page = parse_html(html, BASE)
    assert page.title == "My Page"
    assert page.text == "Hello World"


def test_script_style_comments_removed():
    html = """<body><script>var secret=1;</script><style>.a{}</style>
    <!-- hidden --><p>Visible</p></body>"""
    page = parse_html(html, BASE)
    assert page.text == "Visible"


def test_relative_links_resolved():
    html = """<body>
    <a href="sibling.html">a</a>
    <a href="../about">b</a>
    <a href="/root">c</a>
    <a href="//cdn.example.org/x">d</a>
    <a href="https://other.com/y">e</a></body>"""
    assert parse_html(html, BASE).links == [
        "https://example.com/dir/sibling.html",
        "https://example.com/about",
        "https://example.com/root",
        "https://cdn.example.org/x",
        "https://other.com/y",
    ]


def test_non_http_and_fragment_links_skipped():
    html = """<body>
    <a href="mailto:a@b.com">m</a>
    <a href="javascript:void(0)">j</a>
    <a href="tel:12345">t</a>
    <a href="#top">f</a>
    <a href="">empty</a>
    <a href="/ok">ok</a></body>"""
    assert parse_html(html, BASE).links == ["https://example.com/ok"]


def test_nofollow_skipped():
    html = '<body><a href="/a" rel="nofollow">x</a><a href="/b">y</a></body>'
    assert parse_html(html, BASE).links == ["https://example.com/b"]


def test_base_tag_respected():
    html = """<head><base href="https://other.com/base/"></head>
    <body><a href="x">x</a></body>"""
    assert parse_html(html, BASE).links == ["https://other.com/base/x"]


def test_duplicate_links_deduped_in_order():
    html = '<body><a href="/a">1</a><a href="/b">2</a><a href="/a">3</a></body>'
    assert parse_html(html, BASE).links == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_empty_and_garbage_do_not_crash():
    assert parse_html("", BASE) == ParsedPage()
    assert parse_html("   \n ", BASE) == ParsedPage()
    assert isinstance(
        parse_html("<<<not html>>> <a href=", BASE),
        ParsedPage,
    )


def test_malformed_url_does_not_crash():
    html = '<body><a href="http://[broken">x</a><a href="/ok">y</a></body>'
    assert parse_html(html, BASE).links == ["https://example.com/ok"]