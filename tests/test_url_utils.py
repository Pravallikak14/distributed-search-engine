from crawler.url_utils import host_of, normalize_url


def test_basic_canonicalization():
    assert (
        normalize_url(
            "HTTP://Example.COM:80"
        )
        == "http://example.com/"
    )

    assert (
        normalize_url(
            "HTTPS://Example.COM:443"
        )
        == "https://example.com/"
    )

    assert (
        normalize_url(
            "https://Example.COM:8080"
        )
        == "https://example.com:8080/"
    )

    assert (
        normalize_url(
            "https://Example.COM/path#section"
        )
        == "https://example.com/path"
    )

    assert (
        normalize_url(
            "https://Example.COM"
        )
        == "https://example.com/"
    )


def test_userinfo_removed():
    assert (
        normalize_url(
            "https://user:password@example.com/a"
        )
        == "https://example.com/a"
    )


def test_trailing_dot_host_removed():
    assert (
        normalize_url(
            "https://example.com./a"
        )
        == "https://example.com/a"
    )


def test_ipv6():
    assert (
        normalize_url(
            "http://[2001:db8::1]:80/test"
        )
        == "http://[2001:db8::1]/test"
    )


def test_path_case_preserved():
    assert (
        normalize_url(
            "https://example.com/Hello/World"
        )
        == "https://example.com/Hello/World"
    )


def test_trailing_slash_preserved():
    assert (
        normalize_url(
            "https://example.com/a"
        )
        == "https://example.com/a"
    )

    assert (
        normalize_url(
            "https://example.com/a/"
        )
        == "https://example.com/a/"
    )


def test_tracking_parameters_removed():
    url = (
        "https://example.com/page"
        "?utm_source=google"
        "&utm_medium=cpc"
        "&gclid=123"
        "&fbclid=456"
        "&id=10"
    )

    assert (
        normalize_url(url)
        == "https://example.com/page?id=10"
    )


def test_tracking_parameters_case_insensitive():
    url = (
        "https://example.com/"
        "?UTM_SOURCE=google"
        "&GCLID=123"
        "&page=2"
    )

    assert (
        normalize_url(url)
        == "https://example.com/?page=2"
    )


def test_query_parameters_sorted():
    a = normalize_url(
        "https://example.com/?b=2&a=1"
    )

    b = normalize_url(
        "https://example.com/?a=1&b=2"
    )

    assert a == b
    assert a == "https://example.com/?a=1&b=2"


def test_blank_query_values_preserved():
    assert (
        normalize_url(
            "https://example.com/?a=&b=2"
        )
        == "https://example.com/?a=&b=2"
    )


def test_dot_segments():
    assert (
        normalize_url(
            "https://example.com/a/b/../c/./d"
        )
        == "https://example.com/a/c/d"
    )


def test_percent_encoding():
    assert (
        normalize_url(
            "https://example.com/a%7eb"
        )
        == "https://example.com/a~b"
    )

    assert (
        normalize_url(
            "https://example.com/a%2fb"
        )
        == "https://example.com/a%2Fb"
    )


def test_idn_punycode():
    result = normalize_url(
        "https://münich.com/"
    )

    assert result == "https://xn--mnich-kva.com/"


def test_reject_bad_urls():
    assert normalize_url("") is None

    assert normalize_url(
        "ftp://example.com/"
    ) is None

    assert normalize_url(
        "javascript:alert(1)"
    ) is None

    assert normalize_url(
        "mailto:test@example.com"
    ) is None

    assert normalize_url(
        "/relative/path"
    ) is None

    assert normalize_url(
        "https:///missing-host"
    ) is None


def test_too_long_url():
    long_url = "https://example.com/" + ("a" * 2048)

    assert normalize_url(long_url) is None


def test_idempotent():
    url = (
        "HTTPS://Example.COM:443/a/../b"
        "?utm_source=x&b=2&a=1#test"
    )

    first = normalize_url(url)
    second = normalize_url(first)

    assert first == second


def test_host_of():
    assert (
        host_of("https://example.com/path")
        == "example.com"
    )

    assert (
        host_of("https://example.com:8080/path")
        == "example.com:8080"
    )