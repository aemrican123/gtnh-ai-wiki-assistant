import hashlib
import json

import pytest

from gtnh_assistant.backup import backup, restore
from gtnh_assistant.config import Settings
from gtnh_assistant.extract import Article, Block
from gtnh_assistant.index import Index, chunk_article
from gtnh_assistant.store import Store


class FakeEmbedder:
    name = "deterministic-test-embedder"

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        return [[(v - 128) / 128 for v in hashlib.sha256(t.encode()).digest()[:16]] for t in texts]


def article(revision="1", text="The Electric Blast Furnace uses heating coils and 120 EU/t."):
    return Article(
        "65",
        "https://wiki.gtnewhorizons.com/wiki/Electric_Blast_Furnace",
        "Electric Blast Furnace",
        revision,
        [Block("p", "Usage", "Usage", text)],
        [],
        ["Machines"],
        [],
    )


@pytest.fixture
def kb(tmp_path):
    store = Store(tmp_path)
    settings = Settings(data_dir=tmp_path)
    embedder = FakeEmbedder()
    return store, Index(store, settings, embedder), settings


def test_index_restart_update_and_deleted_vectors(kb):
    store, index, settings = kb
    store.save_article(article(), "raw html")
    index.sync()
    assert store.stats()["chunks"] == 1
    assert index.search("Electric Blast Furnace")[0]["section"] == "Usage"
    calls = index.embedder.calls
    index.sync()
    assert index.embedder.calls == calls
    restarted = Index(Store(settings.data_dir), settings, FakeEmbedder())
    assert restarted.search("Electric Blast Furnace")[0]["url"].endswith("#Usage")
    store.save_article(article("2", "Changed: 480 EU/t."), "updated html")
    assert store.stats()["chunks"] == 0  # stale evidence cannot be served
    index.sync()
    assert index.collection.count() == 1
    assert "480" in index.search("Electric Blast Furnace")[0]["text"]
    store.mark_deleted(article().url)
    assert index.search("Electric Blast Furnace") == []
    index.sync()
    assert index.collection.count() == 0


def test_recover_vector_write_interruption(kb, monkeypatch):
    store, index, _ = kb
    store.save_article(article(), "raw")
    original = index.collection.upsert

    def fail(**kwargs):
        original(**kwargs)
        raise RuntimeError("simulated power loss")

    monkeypatch.setattr(index.collection, "upsert", fail)
    with pytest.raises(RuntimeError):
        index.sync()
    assert store.stats()["indexed_articles"] == 0
    monkeypatch.setattr(index.collection, "upsert", original)
    index.sync()
    assert store.stats()["chunks"] == index.collection.count() == 1


def test_backup_restore_keeps_html_and_vectors(kb, tmp_path):
    store, index, settings = kb
    store.save_article(article(), "original HTML")
    index.sync()
    path = backup(store, tmp_path / "snapshot.zip")
    restored = restore(path, tmp_path / "restored")
    with restored.connect() as db:
        assert db.execute("SELECT html FROM articles").fetchone()[0] == "original HTML"
    settings = settings.model_copy(update={"data_dir": tmp_path / "restored"})
    embedder = FakeEmbedder()
    rebuilt = Index(restored, settings, embedder)
    rebuilt.sync()
    assert embedder.calls == 0
    assert rebuilt.search("Electric Blast Furnace")
    with pytest.raises(ValueError):
        restore(path, tmp_path)


def test_large_table_repeats_headers():
    a = article()
    rows = [[f"Material {i}", f"{i * 100} K"] for i in range(300)]
    a.blocks = [
        Block(
            "table",
            "Heat",
            "Heat",
            "Coils\n" + "\n".join(" | ".join(r) for r in rows),
            rows,
            ["Material", "Temperature"],
        )
    ]
    chunks = chunk_article(a)
    assert len(chunks) > 1
    assert all("Material | Temperature" in c["text"] for c in chunks)
    assert "Material 299 | 29900 K" in chunks[-1]["text"]
    assert json.loads(json.dumps(chunks))[0]["metadata"]["block"] == 0


def test_fts_punctuation_does_not_break_query(kb):
    store, index, _ = kb
    store.save_article(article(), "raw")
    index.sync()
    assert store.keyword('"Electric Blast Furnace" (120 EU/t) - why?')


def test_alias_resolution_and_comparison_coverage(kb):
    store, index, _ = kb
    a = article(text="The Electric Blast Furnace (EBF) is an electric furnace.")
    a.blocks[0].section = "Overview"
    a.blocks.extend(
        [
            Block("p", "Construction", "Construction", "Use 16 Heating Coils and a controller."),
            Block("p", "Usage", "Usage", "Smelting aluminium requires 120 EU/t."),
        ]
    )
    store.save_article(a, "raw")
    b = Article(
        "66",
        "https://wiki.gtnewhorizons.com/wiki/Bricked_Blast_Furnace",
        "Bricked Blast Furnace",
        "1",
        [Block("p", "Overview", "", "A coal-powered steel furnace.")],
        [],
        [],
        [],
    )
    store.save_article(b, "raw")
    index.sync()
    assert store.entities("How does the EBF work?") == {"65": "EBF"}
    assert any(
        "16 Heating Coils" in r["text"]
        for r in index.search("What materials do I need to construct the EBF?")
    )
    results = index.search("Compare the Bricked Blast Furnace and Electric Blast Furnace", limit=2)
    assert {r["article_id"] for r in results} == {"65", "66"}
