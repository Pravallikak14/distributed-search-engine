import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "yclid",
    "_ga",
}

TRACKING_PREFIXES = ("utm_",)

MAX_URL_LEN = 2048

_UNRESERVED = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)

_PCT = re.compile(r"%([0-9a-fA-F]{2})")


def _fix_percent(s: str) -> str:
    def repl(m: re.Match) -> str:
        ch = chr(int(m.group(1), 16))

        if ch in _UNRESERVED:
            return ch

        return "%" + m.group(1).upper()

    return _PCT.sub(repl, s)


def _remove_dot_segments(path: str) -> str:
    segs = path.split("/")[1:]
    out: list[str] = []

    for seg in segs:
        if seg == "..":
            if out:
                out.pop()

        elif seg != ".":
            out.append(seg)

    if segs and segs[-1] in (".", ".."):
        out.append("")

    return "/" + "/".join(out)


def _is_tracking(key: str) -> bool:
    k = key.lower()

    return k in TRACKING_PARAMS or k.startswith(TRACKING_PREFIXES)


def normalize_url(url: str) -> str | None:
    if not url:
        return None

    url = url.strip()

    if not url or len(url) > MAX_URL_LEN:
        return None

    try:
        parts = urlsplit(url)

        scheme = parts.scheme.lower()

        if scheme not in DEFAULT_PORTS:
            return None

        host = (parts.hostname or "").rstrip(".")

        if not host:
            return None

        # Convert international domain names to punycode
        if ":" not in host:
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError:
                pass
        else:
            host = f"[{host}]"

        port = parts.port

        netloc = host

        # Remove default ports
        if port and port != DEFAULT_PORTS[scheme]:
            netloc += f":{port}"

        # Empty path becomes /
        path = parts.path or "/"

        if not path.startswith("/"):
            path = "/" + path

        # Resolve . and .. path segments
        path = _remove_dot_segments(path)

        # Normalize percent encoding
        path = quote(
            path,
            safe="/%:@!$&'()*+,;=~-._"
        )

        path = _fix_percent(path)

        # Parse query parameters
        pairs = [
            (k, v)
            for k, v in parse_qsl(
                parts.query,
                keep_blank_values=True
            )
            if not _is_tracking(k)
        ]

        # Sort query parameters
        query = urlencode(sorted(pairs))

        # Remove fragment
        return urlunsplit(
            (
                scheme,
                netloc,
                path,
                query,
                ""
            )
        )

    except ValueError:
        return None


def host_of(url: str) -> str:
    return urlsplit(url).netloc