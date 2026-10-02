import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from lxml import etree
from lxml import html as lxml_html

ALLOWED_SCHEMES = {"http", "https"}
STRIP_TAGS = ("script", "style", "noscript", "template", "svg", "head")
_WS = re.compile(r"\s+")


@dataclass
class ParsedPage:
    title: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)


def _clean(s: str) -> str:
    return _WS.sub(" ", s).strip()


def parse_html(body: str, base_url: str) -> ParsedPage:
    if not body or not body.strip():
        return ParsedPage()

    try:
        try:
            doc = lxml_html.fromstring(body)
        except ValueError:
            # str with <?xml encoding=...> declaration: lxml needs bytes
            doc = lxml_html.fromstring(body.encode("utf-8", errors="replace"))
    except (etree.LxmlError, ValueError):
        return ParsedPage()

    # 1. Title + base (head ki munde, strip cheyyakamunde)
    title = _clean(doc.findtext(".//title") or "")
    base_tag = doc.find(".//base")
    if base_tag is not None and base_tag.get("href"):
        base_url = urljoin(base_url, base_tag.get("href").strip())

    # 2. Links
    seen: dict[str, None] = {}
    for a in doc.iterfind(".//a[@href]"):
        href = a.get("href").strip()
        if not href or href.startswith("#"):
            continue
        if "nofollow" in (a.get("rel") or "").lower():
            continue
        try:
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
        except ValueError:  # e.g. malformed IPv6 "http://[abc"
            continue
        if parsed.scheme in ALLOWED_SCHEMES and parsed.netloc:
            seen[absolute] = None

    # 3. Text
    etree.strip_elements(
        doc, etree.Comment, etree.ProcessingInstruction, *STRIP_TAGS,
        with_tail=False,
    )
    text = _clean(" ".join(doc.itertext()))

    return ParsedPage(title=title, text=text, links=list(seen))