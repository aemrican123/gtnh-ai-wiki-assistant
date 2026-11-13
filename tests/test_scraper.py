from threading import Event

import httpx
import pytest
from protego import Protego

from gtnh_assistant.config import Settings
from gtnh_assistant.extract import BASE, article_url, extract
from gtnh_assistant.scrape import AccessDenied, Fetcher, crawl
from gtnh_assistant.store import Store

HTML = """<html><head><link rel="canonical" href="https://wiki.gtnewhorizons.com/wiki/Test"/>
<script>var config={"wgArticleId":42,"wgRevisionId":100};</script></head>
<h1 id="firstHeading">Test machine</h1><div class="mw-parser-output">
<p>Use 32 EU/t.</p><h2 id="Construction">Construction</h2><ol><li>Build casing</li><li>Add hatch</li></ol>
<table><caption>Coils</caption><tr><th>Material</th><th>Heat</th></tr>
<tr><td rowspan="2"><img alt="Kanthal" src="/x.png"/></td><td>2700 K</td></tr>
<tr><td>3600 K</td></tr></table><a href="/wiki/Other">Other</a>
<div class="navbox"><p>Unwanted navigation</p></div></div>
<div id="mw-normal-catlinks"><ul><li><a>Machines</a></li></ul></div></html>"""


def test_extract_structured_content():
    a = extract(HTML, BASE + "/wiki/Test")
    assert a.id == "42" and a.revision == "100"
    assert a.categories == ["Machines"]
    assert a.images[0]["alt"] == "Kanthal"
    table = next(b for b in a.blocks if b.kind == "table")
    assert table.rows[-1] == ["Kanthal", "3600 K"]
    assert table.headers == ["Material", "Heat"]
    assert table.anchor == "Construction"
    assert "Unwanted navigation" not in str(a.blocks)
    assert "32 EU/t" in a.blocks[0].text


def test_url_scope():
    assert article_url("/wiki/Electric_Blast_Furnace#Usage") == BASE + "/wiki/Electric_Blast_Furnace"
    assert article_url("/wiki/Test?action=edit") is None
    assert article_url("/wiki/Special:AllPages") is None
    assert article_url("https://evil.example/wiki/Test") is None


def test_robots_wildcards_and_redirects():
    transport = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": BASE + "/w/api.php"}))
    f = Fetcher(interval=0, client=httpx.Client(transport=transport))
    f.rules = Protego.parse("User-agent: *\nDisallow: /w/\nDisallow: /*?action=\n")
    with pytest.raises(AccessDenied):
        f.get(BASE + "/wiki/Test")
    with pytest.raises(AccessDenied):
        f.get(BASE + "/wiki/Test?action=edit")


def test_resume_idempotency_and_delete(tmp_path):
    store = Store(tmp_path)
    settings = Settings(data_dir=tmp_path)
    status = [200]

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(status[0], text=HTML)

    def fetcher():
        return Fetcher(interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))

    crawl(store, settings, seeds=[BASE + "/wiki/Test"], limit=1, fetcher=fetcher())
    assert Store(tmp_path).stats()["articles"] == 1
    assert store.stats()["pending"] == 1
    store.start_update()
    result = crawl(store, settings, limit=1, fetcher=fetcher())
    assert result["changed"] == 0
    status[0] = 404
    store.start_update()
    crawl(store, settings, limit=1, fetcher=fetcher())
    assert store.stats()["articles"] == 0


def test_cancel_leaves_queue(tmp_path):
    stop = Event()
    stop.set()
    store = Store(tmp_path)
    crawl(store, Settings(data_dir=tmp_path), seeds=[BASE + "/wiki/Test"], stop=stop)
    assert store.stats()["pending"] == 1


def test_redirect_alias_does_not_delete_target(tmp_path):
    store = Store(tmp_path)
    store.save_article(extract(HTML, BASE + "/wiki/Test"), HTML, BASE + "/wiki/Alias")
    store.mark_deleted(BASE + "/wiki/Alias")
    assert store.stats()["articles"] == 1


def test_portable_infobox_does_not_pollute_headings():
    extra = """<aside class="portable-infobox"><h2>Machine</h2><div class="pi-data">
    <h3 class="pi-data-label">Size</h3><div class="pi-data-value">3 x 3 x 4</div></div>
    <div class="pi-data"><h3 class="pi-data-label">Source</h3><div class="pi-data-value">
    <a class="external" href="https://example.org/source">Source code</a></div></div></aside>"""
    a = extract(HTML.replace("<p>Use 32 EU/t.</p>", extra + "<p>Use 32 EU/t.</p>"), BASE + "/wiki/Test")
    assert a.blocks[0].section == "Specifications"
    assert "Size: 3 x 3 x 4" in a.blocks[0].text
    assert a.blocks[1].section == "Overview"
    assert a.references == [{"label": "Source code", "url": "https://example.org/source"}]


def test_category_members_outside_article_body():
    html = '<h1 id="firstHeading">Category:Machines</h1><div class="mw-parser-output"></div>'
    html += '<div class="mw-category"><a href="/wiki/Test">Test</a></div>'
    a = extract(html, BASE + "/wiki/Category:Machines")
    assert a.blocks[0].text == "Test"
    assert a.links == [BASE + "/wiki/Test"]


def test_page_title_recreated_under_new_id(tmp_path):
    store = Store(tmp_path)
    store.save_article(extract(HTML, BASE + "/wiki/Test"), HTML)
    newer = HTML.replace('"wgArticleId":42', '"wgArticleId":43')
    store.save_article(extract(newer, BASE + "/wiki/Test"), newer)
    assert store.stats()["articles"] == 1
    assert store.article("43").title == "Test machine"
