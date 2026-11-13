"""Loss-aware HTML extraction. Raw snapshots remain the authoritative reference."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

BASE = "https://wiki.gtnewhorizons.com"
PARSER_VERSION = "3"
EXCLUDED_NAMESPACES = {
    "special",
    "user",
    "user talk",
    "talk",
    "template",
    "template talk",
    "file",
    "file talk",
    "mediawiki",
    "mediawiki talk",
    "help",
    "help talk",
    "module",
    "module talk",
    "category talk",
    "gt new horizons",
    "gt new horizons talk",
}


def article_url(url: str, base: str = BASE) -> str | None:
    p = urlsplit(urljoin(base, url))
    if p.scheme != "https" or p.netloc != urlsplit(BASE).netloc or not p.path.startswith("/wiki/"):
        return None
    if p.query:
        return None
    title = unquote(p.path[6:]).replace("_", " ")
    if not title or title.split(":", 1)[0].lower() in EXCLUDED_NAMESPACES:
        return None
    return urlunsplit(("https", p.netloc, quote(unquote(p.path).replace(" ", "_"), safe="/:()'!,"), "", ""))


@dataclass
class Block:
    kind: str
    section: str
    anchor: str
    text: str
    rows: list[list[str]] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)


@dataclass
class Article:
    id: str
    url: str
    title: str
    revision: str
    blocks: list[Block]
    links: list[str]
    categories: list[str]
    images: list[dict]
    disambiguation: bool = False
    license: str = "CC BY-SA 4.0 unless otherwise noted"
    references: list[dict] = field(default_factory=list)

    def serialize(self):
        return asdict(self)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.serialize(), sort_keys=True).encode()).hexdigest()


def text_of(node):
    # Image-only item cells often carry their item name in alt/title.
    clone = BeautifulSoup(str(node), "lxml")
    for img in clone.find_all("img"):
        img.replace_with(img.get("alt") or img.get("title") or "[unlabelled image]")
    return re.sub(r"[ \t]+", " ", clone.get_text(" ", strip=True)).strip()


def table_grid(table):
    """Expand row/column spans so each row preserves its label associations."""
    spans = {}
    rows = []
    header_rows = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = tr.find_all(["td", "th"], recursive=False)
        row, col = [], 0
        for cell in cells:
            while col in spans:
                value, remaining = spans.pop(col)
                row.append(value)
                if remaining > 1:
                    spans[col] = (value, remaining - 1)
                col += 1
            value = text_of(cell)
            try:
                width = min(100, max(1, int(cell.get("colspan", 1))))
                height = min(1000, max(1, int(cell.get("rowspan", 1))))
            except ValueError:
                width, height = 1, 1
            for _ in range(width):
                row.append(value)
                if height > 1:
                    spans[col] = (value, height - 1)
                col += 1
        while col in spans:
            value, remaining = spans.pop(col)
            row.append(value)
            if remaining > 1:
                spans[col] = (value, remaining - 1)
            col += 1
        if row:
            if cells and all(c.name == "th" for c in cells):
                header_rows.append(row)
            rows.append(row)
    headers = header_rows[-1] if header_rows else []
    return rows, headers


def extract(html: str, url: str) -> Article:
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one(".mw-parser-output")
    if root is None or soup.select_one(".noarticletext"):
        raise ValueError("No wiki article content found")
    canonical = soup.find("link", rel="canonical")
    url = article_url(canonical.get("href", "")) if canonical else article_url(url)
    if not url:
        raise ValueError("Article canonical URL is out of scope")
    title_node = soup.select_one(".mw-page-title-main, #firstHeading")
    title = title_node.get_text(" ", strip=True) if title_node else unquote(url.rsplit("/", 1)[-1])

    def metadata(name, default=""):
        match = re.search(r'"' + name + r'"\s*:\s*("[^"\n]*"|\d+)', html)
        return str(json.loads(match.group(1))) if match else default

    links = sorted({u for a in root.select("a[href]") if (u := article_url(a["href"], url))})
    category_members = soup.select(".mw-category a[href]")
    links = sorted(set(links) | {u for a in category_members if (u := article_url(a["href"], url))})
    references = [
        {"label": a.get_text(" ", strip=True), "url": urljoin(url, a["href"])}
        for a in root.select("a.external[href]")
        if urlsplit(urljoin(url, a["href"])).scheme in {"https", "http"}
    ]
    categories = [a.get_text(" ", strip=True) for a in soup.select("#mw-normal-catlinks ul a")]
    images = [
        {"url": urljoin(url, i.get("src", "")), "alt": i.get("alt", ""), "title": i.get("title", "")}
        for i in root.select("img[src]")
    ]
    for el in root.select("script, style, .mw-editsection, .navbox, .toc, #toc, .noprint"):
        el.decompose()
    blocks, headings = [], []
    # PortableInfobox stores values in divs, not paragraphs or HTML tables.
    # Its decorative h2/h3 labels must not become article section headings.
    for box in root.select(".portable-infobox"):
        values = []
        for item in box.select(".pi-data"):
            label = item.select_one(".pi-data-label")
            value = item.select_one(".pi-data-value")
            if label and value:
                values.append(f"{text_of(label)}: {text_of(value)}")
        if values:
            blocks.append(Block("infobox", "Specifications", "", "\n".join(values)))
        box.decompose()
    anchor = ""
    for node in root.find_all(["h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "dl", "figure"]):
        if any(p.name in {"table", "ul", "ol", "dl", "figure"} for p in node.parents if p is not root):
            continue
        if re.fullmatch("h[2-6]", node.name):
            level = int(node.name[1])
            headings = [(n, t) for n, t in headings if n < level]
            headings.append((level, node.get_text(" ", strip=True)))
            id_node = node.find(id=True)
            anchor = node.get("id") or (id_node.get("id") if id_node else "")
            continue
        section = " > ".join(t for _, t in headings) or "Overview"
        text = text_of(node)
        if not text:
            continue
        if node.name == "table":
            rows, headers = table_grid(node)
            caption = node.find("caption")
            prefix = text_of(caption) + "\n" if caption else ""
            rendered = prefix + "\n".join(" | ".join(row) for row in rows)
            blocks.append(Block("table", section, anchor, rendered, rows, headers))
        else:
            if node.name in {"ul", "ol"}:
                text = "\n".join(
                    f"{i}. {text_of(li)}" for i, li in enumerate(node.find_all("li", recursive=False), 1)
                )
            blocks.append(Block(node.name, section, anchor, text))
    if not blocks:
        if category_members:
            blocks.append(
                Block(
                    "ul",
                    "Category members",
                    "",
                    "\n".join(a.get_text(" ", strip=True) for a in category_members),
                )
            )
        else:
            raise ValueError("Article has no extractable content")
    article = Article(
        metadata("wgArticleId", url),
        url,
        title,
        metadata("wgRevisionId"),
        blocks,
        links,
        categories,
        images,
        any("disambiguation" in c.lower() for c in categories),
    )
    article.references = references
    return article
