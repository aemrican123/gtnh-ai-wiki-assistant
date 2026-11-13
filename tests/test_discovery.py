import gzip

import httpx
import pytest

from gtnh_assistant.scrape import AccessDenied, Fetcher

BASE = "https://wiki.gtnewhorizons.com"
CDN = "https://static.wikitide.net"


def test_advertised_cdn_sitemap_checks_robots_and_filters_namespaces():
    requests = []

    def handler(req):
        requests.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml")
        if req.url.path == "/sitemap.xml":
            return httpx.Response(
                200,
                text=f"<sitemapindex><sitemap><loc>{BASE}/sitemaps/wiki.gz</loc></sitemap></sitemapindex>",
            )
        if req.url.path == "/sitemaps/wiki.gz":
            return httpx.Response(301, headers={"location": CDN + "/gtnhwiki/sitemaps/wiki.gz"})
        return httpx.Response(
            200,
            content=gzip.compress(
                f"<urlset><url><loc>{BASE}/wiki/EBF</loc></url><url><loc>{BASE}/wiki/Template:Box</loc></url></urlset>".encode()
            ),
        )

    f = Fetcher(interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert f.discover() == [BASE + "/wiki/EBF"]
    assert CDN + "/robots.txt" in requests
    with pytest.raises(AccessDenied):
        f.get(CDN + "/gtnhwiki/sitemaps/wiki.gz")


def test_cdn_disallow_stops_fetch():
    def handler(req):
        if req.url.host == "static.wikitide.net":
            return httpx.Response(200, text="User-agent: *\nDisallow: /gtnhwiki/")
        return httpx.Response(200, text="User-agent: *\nAllow: /")

    f = Fetcher(interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AccessDenied):
        f.get(CDN + "/gtnhwiki/sitemaps/wiki.gz", sitemap=True)
