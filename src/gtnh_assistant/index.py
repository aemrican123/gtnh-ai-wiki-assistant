import hashlib
import json
import os
import re
from pathlib import Path
from threading import RLock
from urllib.parse import quote

import tiktoken

from .extract import PARSER_VERSION, Block

os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path("data/tokenizers").resolve()))
ENCODING = tiktoken.get_encoding("cl100k_base")


def tokens(text):
    return len(ENCODING.encode(text, disallowed_special=()))


def trim(text, budget):
    return ENCODING.decode(ENCODING.encode(text, disallowed_special=())[: max(0, budget)])


def split_text(text, budget=450):
    pieces = re.split(r"(?<=[.!?])\s+|\n", text)
    current = ""
    for piece in pieces:
        if tokens(current + "\n" + piece) <= budget:
            current = (current + "\n" + piece).strip()
            continue
        if current:
            yield current
            current = ""
        encoded = ENCODING.encode(piece, disallowed_special=())
        while len(encoded) > budget:
            yield ENCODING.decode(encoded[:budget])
            encoded = encoded[budget:]
        current = ENCODING.decode(encoded)
    if current:
        yield current


def chunk_article(article):
    chunks = []
    groups = []
    for block_index, block in enumerate(article.blocks):
        if (
            groups
            and block.kind not in {"table", "infobox"}
            and groups[-1][1].kind not in {"table", "infobox"}
            and groups[-1][1].section == block.section
            and tokens(groups[-1][1].text + block.text) < 450
        ):
            previous = groups[-1][1]
            previous.text += "\n" + block.text
        else:
            groups.append(
                (
                    block_index,
                    Block(block.kind, block.section, block.anchor, block.text, block.rows, block.headers),
                )
            )
    for block_index, block in groups:
        if block.kind == "table" and tokens(block.text) > 600 and block.rows:
            # Rows remain atomic; repeat column labels and retain parent block reference.
            caption = block.text.split("\n", 1)[0] if "\n" in block.text else ""
            prefix = caption + "\n" + " | ".join(block.headers) + "\n"
            parts, part = [], prefix
            for row in block.rows:
                line = " | ".join(row)
                if tokens(part + line) > 600 and part != prefix:
                    parts.append(part)
                    part = prefix
                part += line + "\n"
            if part != prefix:
                parts.append(part)
        elif block.kind in {"table", "ol", "ul"}:
            parts = [block.text] if tokens(block.text) <= 900 else list(split_text(block.text, 700))
        else:
            parts = list(split_text(block.text))
        for part_index, content in enumerate(parts):
            ident = hashlib.sha256(
                f"{article.id}:{article.digest}:{block_index}:{part_index}".encode()
            ).hexdigest()
            url = article.url + ("#" + quote(block.anchor, safe="_-.:") if block.anchor else "")
            chunks.append(
                {
                    "id": ident,
                    "article_id": article.id,
                    "section": block.section,
                    "url": url,
                    "text": content,
                    "digest": article.digest,
                    "metadata": {
                        "title": article.title,
                        "categories": json.dumps(article.categories),
                        "revision": article.revision,
                        "block": block_index,
                        "kind": block.kind,
                        "parser_version": PARSER_VERSION,
                    },
                }
            )
    return chunks


class LocalEmbedder:
    def __init__(self, name, cache_dir):
        self.name = name
        self.cache_dir = cache_dir
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            try:
                self._model = SentenceTransformer(
                    self.name, cache_folder=str(self.cache_dir), device="cpu", local_files_only=True
                )
            except OSError:
                self._model = SentenceTransformer(self.name, cache_folder=str(self.cache_dir), device="cpu")
        return self._model

    def encode(self, texts):
        import numpy as np

        # Embed every window rather than silently truncating long tables at 256 wordpieces.
        model = self.model
        windows, groups = [], []
        size = model.max_seq_length - 2
        for text in texts:
            ids = model.tokenizer.encode(text, add_special_tokens=False, verbose=False)
            start = len(windows)
            for offset in range(0, max(1, len(ids)), size):
                windows.append(model.tokenizer.decode(ids[offset : offset + size]))
            groups.append((start, len(windows)))
        vectors = model.encode(windows, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        result = []
        for start, end in groups:
            vector = np.mean(vectors[start:end], axis=0)
            vector /= max(float(np.linalg.norm(vector)), 1e-12)
            result.append(vector.tolist())
        return result


class Index:
    def __init__(self, store, settings, embedder=None):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.store = store
        self.settings = settings
        self.lock = RLock()
        self.embedder = embedder or LocalEmbedder(settings.embedding_model, settings.data_dir / "models")
        self.model_key = hashlib.sha256((self.embedder.name + ":window-mean-v1").encode()).hexdigest()[:16]
        self.client = chromadb.PersistentClient(
            path=str(settings.data_dir / "chroma"), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            "wiki_" + self.model_key, metadata={"hnsw:space": "cosine"}
        )
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS embedding_cache (id TEXT PRIMARY KEY, vector TEXT)")

    def embeddings(self, texts):
        keys = [hashlib.sha256((self.model_key + text).encode()).hexdigest() for text in texts]
        cached = {}
        with self.store.connect() as db:
            for key in keys:
                row = db.execute("SELECT vector FROM embedding_cache WHERE id=?", (key,)).fetchone()
                if row:
                    cached[key] = json.loads(row[0])
        missing = {k: t for k, t in zip(keys, texts) if k not in cached}
        if missing:
            values = self.embedder.encode(list(missing.values()))
            cached.update(zip(missing, values))
            with self.store.connect() as db:
                db.executemany(
                    "INSERT OR REPLACE INTO embedding_cache VALUES (?,?)",
                    [(k, json.dumps(cached[k])) for k in missing],
                )
        return [cached[k] for k in keys]

    def sync(self, stop=None, progress=lambda _: None, rebuild=False):
        self.store.reparse(progress)
        if (
            rebuild
            or self.store.get("embedding_model") != self.model_key
            or self.store.get("chunker_version") != "2"
        ):
            with self.store.connect() as db:
                db.execute("UPDATE articles SET indexed_digest=''")
            self.store.set("embedding_model", self.model_key)
            self.store.set("chunker_version", "2")
        completed = 0
        for row in self.store.dirty_articles():
            if stop and stop.is_set():
                break
            article = self.store.article(row["id"])
            progress(f"Indexing {article.title}")
            self.store.set("progress", f"Indexing {article.title}")
            chunks = [] if row["deleted"] else chunk_article(article)
            texts = [article.title + "\n" + c["section"] + "\n" + c["text"] for c in chunks]
            with self.lock:
                vectors = self.embeddings(texts) if texts else []
                # Idempotent vectors first, then a single SQLite commit. Dirty state survives a crash.
                for start in range(0, len(chunks), 128):
                    batch = chunks[start : start + 128]
                    self.collection.upsert(
                        ids=[c["id"] for c in batch],
                        embeddings=vectors[start : start + 128],
                        metadatas=[{"article_id": article.id} for c in batch],
                    )
                with self.store.connect() as db:
                    old = [
                        r[0] for r in db.execute("SELECT id FROM chunks WHERE article_id=?", (article.id,))
                    ]
                    db.executemany("DELETE FROM chunks_fts WHERE id=?", [(i,) for i in old])
                    db.execute("DELETE FROM chunks WHERE article_id=?", (article.id,))
                    for c in chunks:
                        db.execute(
                            "INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
                            (
                                c["id"],
                                article.id,
                                c["section"],
                                c["url"],
                                c["text"],
                                c["digest"],
                                json.dumps(c["metadata"]),
                            ),
                        )
                        db.execute(
                            "INSERT INTO chunks_fts VALUES (?,?,?,?)",
                            (c["id"], article.title, c["section"], c["text"]),
                        )
                    db.execute("UPDATE articles SET indexed_digest=? WHERE id=?", (row["digest"], article.id))
                valid = {c["id"] for c in chunks}
                existing = self.collection.get(where={"article_id": article.id})["ids"]
                obsolete = [i for i in existing if i not in valid]
                if obsolete:
                    self.collection.delete(ids=obsolete)
            completed += 1
        return {"indexed": completed}

    def search(self, query, limit=None):
        limit = limit or self.settings.retrieval_limit
        keyword = self.store.keyword(query, 30)
        entities = self.store.entities(query)
        entity_ids = []
        if entities:
            with self.store.connect() as db:
                entity_ids = [
                    r[0]
                    for r in db.execute(
                        f"SELECT id FROM chunks WHERE article_id IN ({','.join('?' for _ in entities)})",
                        list(entities),
                    )
                ]
        with self.lock:
            count = self.collection.count()
            semantic = (
                self.collection.query(query_embeddings=self.embeddings([query]), n_results=min(30, count))[
                    "ids"
                ][0]
                if count
                else []
            )
        scores = {}
        for ranking in (keyword, semantic):
            for rank, ident in enumerate(ranking):
                scores[ident] = scores.get(ident, 0) + 1 / (60 + rank)
        for ident in entity_ids:
            scores.setdefault(ident, 0)
        ordered = sorted(scores, key=scores.get, reverse=True)
        candidates = self.store.chunks(ordered)
        q = query.casefold()
        for name in entities.values():
            q = re.sub(re.escape(name.casefold()), " ", q)
        stopwords = {
            "what",
            "which",
            "how",
            "does",
            "do",
            "the",
            "a",
            "an",
            "it",
            "work",
            "works",
            "explain",
            "is",
            "are",
            "of",
            "to",
            "in",
            "for",
            "and",
            "between",
            "difference",
            "i",
            "need",
            "with",
            "many",
            "much",
            "me",
            "about",
            "tell",
        }
        terms = {w for w in re.findall(r"[\w]+", q) if w not in stopwords and len(w) > 1}
        construction = bool(re.search(r"\b(build|construct|construction|materials|structure)\b", q))
        broad = not terms or "difference" in query.casefold()

        def rank(c):
            text = c["text"].casefold()
            section = c["section"].casefold()
            lexical = sum(1 for t in terms if re.search(r"\b" + re.escape(t), section + " " + text)) / max(
                1, len(terms)
            )
            bonus = 0.8 if construction and "construction" in section else 0
            if broad:
                bonus += {"overview": 1.0, "specifications": 0.4, "usage": 0.5}.get(section, 0)
            # Tiny labels and isolated illustration captions are poor answer evidence.
            penalty = 1.0 if tokens(c["text"]) < 20 else 0
            return (int(c["article_id"] in entities), lexical + bonus + 10 * scores[c["id"]] - penalty)

        candidates.sort(key=rank, reverse=True)
        if len(entities) > 1:
            # Reserve evidence for each named subject before filling remaining slots.
            reserved = []
            for article_id in entities:
                reserved.extend(
                    [c for c in candidates if c["article_id"] == article_id][: max(1, limit // len(entities))]
                )
            reserved_ids = {c["id"] for c in reserved}
            candidates = reserved + [c for c in candidates if c["id"] not in reserved_ids]
        result, seen = [], set()
        for c in candidates:
            normalized = re.sub(r"\s+", " ", c["text"]).strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(c)
            if len(result) == limit:
                break
        return result
