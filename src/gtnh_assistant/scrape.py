import gzip
import time
from threading import Event
from urllib.parse import urljoin, urlsplit

import httpx
from lxml import etree
from protego import Protego

from .extract import BASE, article_url, extract

USER_AGENT = "GTNHKnowledgeAssistant/0.1 (personal local wiki index)"


class AccessDenied(RuntimeError):
    """The site refused access (or its rules could not be read): stop collecting entirely."""


class Disallowed(AccessDenied):
    """robots.txt or the redirect policy rules out one URL. Skip that URL; keep collecting the rest."""


class Fetcher:
    def __init__(self, interval=2.0, client=None, stop=None):
        self.client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
        self.interval = interval
        self.stop = stop or Event()
        self.rules = None
        self.cdn_rules = None
        self.last_request = 0.0

    def close(self):
        self.client.close()

    def _get(self, url, headers=None):
        for attempt in range(4):
            if self.stop.wait(max(0, self.interval - (time.monotonic() - self.last_request))):
                raise InterruptedError("Collection cancelled")
            self.last_request = time.monotonic()
            try:
                response = self.client.get(url, headers=headers, follow_redirects=False)
            except httpx.TransportError:
                if attempt == 3:
                    raise
                if self.stop.wait(2**attempt):
                    raise InterruptedError("Collection cancelled")
                continue
            if response.status_code in {401, 403}:
                raise AccessDenied(f"Site denied access ({response.status_code}); collection stopped")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 3:
                    response.raise_for_status()
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = max(2**attempt, float(retry))
                except ValueError:
                    from email.utils import parsedate_to_datetime

                    try:
                        delay = max(2**attempt, parsedate_to_datetime(retry).timestamp() - time.time())
                    except (TypeError, ValueError):
                        delay = 2**attempt
                if delay > 300:
                    raise RuntimeError("Server requested a long retry delay; resume later")
                if self.stop.wait(delay):
                    raise InterruptedError("Collection cancelled")
                continue
            return response
        raise RuntimeError("Request retries exhausted")

    def load_robots(self):
        response = self._get(BASE + "/robots.txt")
        response.raise_for_status()  # fail closed if robots cannot be read
        if "<html" in response.text.lower():
            raise AccessDenied("robots.txt returned HTML; collection stopped")
        self.rules = Protego.parse(response.text)
        delay = self.rules.crawl_delay(USER_AGENT)
        if delay:
            self.interval = max(self.interval, float(delay))
        return [u for u in self.rules.sitemaps if urlsplit(u).netloc == urlsplit(BASE).netloc]

    def get(self, url, headers=None, sitemap=False):
        if self.rules is None:
            self.load_robots()
        for _ in range(6):
            parts = urlsplit(url)
            cdn_sitemap = (
                sitemap
                and parts.netloc == "static.wikitide.net"
                and parts.path.startswith("/gtnhwiki/sitemaps/")
            )
            if parts.scheme != "https" or (parts.netloc != urlsplit(BASE).netloc and not cdn_sitemap):
                raise Disallowed(f"Cross-site redirect refused: {url}")
            rules = self.rules
            if cdn_sitemap:
                if self.cdn_rules is None:
                    robots = self._get("https://static.wikitide.net/robots.txt")
                    if robots.status_code not in {404, 410}:
                        robots.raise_for_status()
                        if "<html" in robots.text.lower():
                            raise AccessDenied("Sitemap host robots.txt returned HTML")
                    self.cdn_rules = Protego.parse(robots.text if robots.status_code == 200 else "")
                    delay = self.cdn_rules.crawl_delay(USER_AGENT)
                    if delay:
                        self.interval = max(self.interval, float(delay))
                rules = self.cdn_rules
            if not rules.can_fetch(url, USER_AGENT):
                raise Disallowed(f"robots.txt disallows {url}")
            response = self._get(url, headers)
            if response.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers["location"])
                headers = None
                continue
            return response
        raise RuntimeError("Redirect loop or too many redirects")

    def discover(self):
        pending = self.load_robots() or [BASE + "/sitemap.xml"]
        seen, articles = set(), set()
        while pending:
            url = pending.pop()
            if url in seen:
                continue
            seen.add(url)
            response = self.get(url, sitemap=True)
            response.raise_for_status()
            body = response.content
            if body.startswith(b"\x1f\x8b"):
                body = gzip.decompress(body)
            root = etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False, no_network=True))
            locations = root.xpath("//*[local-name()='loc']/text()")
            if etree.QName(root).localname == "sitemapindex":
                pending.extend(locations)
            else:
                articles.update(u for loc in locations if (u := article_url(loc)))
        return sorted(articles)


def crawl(
    store, settings, limit=None, update=False, seeds=None, stop=None, progress=lambda _: None, fetcher=None
):
    stop = stop or Event()
    fetcher = fetcher or Fetcher(settings.request_interval, stop=stop)
    count = changed = 0
    try:
        if update:
            store.start_update()
        if seeds:
            store.enqueue([u for s in seeds if (u := article_url(s))])
        elif update or not store.stats()["pending"]:
            progress("Reading sitemap")
            store.enqueue(fetcher.discover())
        while not stop.is_set() and (limit is None or count < limit):
            item = store.next_url()
            if not item:
                break
            url = item["url"]
            progress(f"Fetching {url}")
            store.set("progress", f"Fetching {url}")
            try:
                headers = {}
                if item["etag"]:
                    headers["If-None-Match"] = item["etag"]
                if item["modified"]:
                    headers["If-Modified-Since"] = item["modified"]
                response = fetcher.get(url, headers)
                if response.status_code in {404, 410}:
                    store.mark_deleted(url)
                elif response.status_code != 304:
                    response.raise_for_status()
                    article = extract(response.text, str(response.url))
                    changed += store.save_article(article, response.text, url)
                    store.enqueue(article.links)
                store.finish_url(
                    url, etag=response.headers.get("etag"), modified=response.headers.get("last-modified")
                )
            except Disallowed as exc:
                # e.g. an article that redirects to a disallowed Special: page. Never fetched; skip it.
                store.finish_url(url, "skipped", str(exc)[:500])
                progress(f"Skipped {url}: {exc}")
            except (AccessDenied, InterruptedError):
                raise
            except Exception as exc:
                store.finish_url(url, "error", f"{type(exc).__name__}: {exc}"[:500])
            count += 1
        return {"processed": count, "changed": changed, "cancelled": stop.is_set()}
    finally:
        fetcher.close()
