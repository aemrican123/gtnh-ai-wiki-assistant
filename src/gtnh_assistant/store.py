import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

from .extract import PARSER_VERSION, Article, Block


def now():
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, data_dir):
        self.directory = Path(data_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "knowledge.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY, url TEXT UNIQUE, title TEXT, revision TEXT,
                    digest TEXT, payload TEXT, html TEXT, updated TEXT, deleted INTEGER DEFAULT 0,
                    parser_version TEXT, indexed_digest TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS aliases (url TEXT PRIMARY KEY, article_id TEXT);
                CREATE TABLE IF NOT EXISTS names (name TEXT,article_id TEXT,PRIMARY KEY(name,article_id));
                CREATE TABLE IF NOT EXISTS frontier (
                    url TEXT PRIMARY KEY, state TEXT DEFAULT 'pending', error TEXT DEFAULT '',
                    attempts INTEGER DEFAULT 0, etag TEXT, modified TEXT, checked TEXT);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, article_id TEXT, section TEXT, url TEXT, text TEXT,
                    digest TEXT, metadata TEXT);
                CREATE INDEX IF NOT EXISTS chunks_article ON chunks(article_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, title, section, text);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, created TEXT, payload TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, urls):
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO frontier(url) VALUES (?)", [(u,) for u in urls])

    def start_update(self):
        with self.connect() as db:
            db.execute("UPDATE frontier SET state='pending', error='', attempts=0")

    def retry_errors(self):
        with self.connect() as db:
            db.execute("UPDATE frontier SET state='pending', error='', attempts=0 WHERE state='error'")

    def reparse(self, progress=lambda _: None):
        from .extract import extract

        with self.connect() as db:
            rows = list(
                db.execute(
                    "SELECT url,html FROM articles WHERE deleted=0 AND parser_version!=?", (PARSER_VERSION,)
                )
            )
        for row in rows:
            progress(f"Reprocessing saved article {row['url']}")
            self.save_article(extract(row["html"], row["url"]), row["html"])

    def next_url(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM frontier WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
            return dict(row) if row else None

    def finish_url(self, url, state="done", error="", etag=None, modified=None):
        with self.connect() as db:
            db.execute(
                """UPDATE frontier SET state=?,error=?,attempts=attempts+1,checked=?,
                etag=COALESCE(?,etag),modified=COALESCE(?,modified) WHERE url=?""",
                (state, error, now(), etag, modified, url),
            )

    def save_article(self, article, html, requested_url=None):
        payload = json.dumps(article.serialize(), ensure_ascii=False)
        with self.connect() as db:
            old = db.execute("SELECT digest,deleted FROM articles WHERE id=?", (article.id,)).fetchone()
            changed = not old or old["digest"] != article.digest or old["deleted"]
            # A deleted page title may be reused by a newly created page ID.
            db.execute(
                "UPDATE articles SET deleted=1,url=NULL WHERE url=? AND id!=?", (article.url, article.id)
            )
            db.execute(
                """INSERT INTO articles(id,url,title,revision,digest,payload,html,updated,parser_version)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                url=excluded.url,title=excluded.title,revision=excluded.revision,digest=excluded.digest,
                payload=excluded.payload,html=excluded.html,updated=excluded.updated,deleted=0,
                parser_version=excluded.parser_version""",
                (
                    article.id,
                    article.url,
                    article.title,
                    article.revision,
                    article.digest,
                    payload,
                    html,
                    now(),
                    PARSER_VERSION,
                ),
            )
            if requested_url:
                previous = db.execute(
                    "SELECT id FROM articles WHERE url=? AND id!=?", (requested_url, article.id)
                ).fetchone()
                if previous:
                    db.execute("UPDATE articles SET deleted=1 WHERE id=?", (previous["id"],))
                db.execute("INSERT OR REPLACE INTO aliases VALUES (?,?)", (requested_url, article.id))
            names = {article.title}
            names.update(re.findall(r"\(([A-Za-z0-9/-]{2,12})\)$", article.title))
            if requested_url:
                names.add(unquote(requested_url.rsplit("/", 1)[-1]).replace("_", " "))
            intro = " ".join(b.text for b in article.blocks if b.section == "Overview")[:4000]
            names.update(re.findall(re.escape(article.title) + r"\s*\(([A-Za-z0-9/-]{2,12})\)", intro))
            db.executemany("INSERT OR IGNORE INTO names VALUES (?,?)", [(n, article.id) for n in names])
        return changed

    def entities(self, query):
        with self.connect() as db:
            names = list(
                db.execute(
                    "SELECT n.name,n.article_id FROM names n JOIN articles a ON a.id=n.article_id WHERE a.deleted=0"
                )
            )
        matches, occupied = {}, []
        for row in sorted(names, key=lambda r: len(r["name"]), reverse=True):
            if len(row["name"]) < 2:
                continue
            for match in re.finditer(r"(?<!\w)" + re.escape(row["name"]) + r"(?!\w)", query, re.IGNORECASE):
                if any(match.start() < end and match.end() > start for start, end in occupied):
                    continue
                occupied.append(match.span())
                matches[row["article_id"]] = row["name"]
        return matches

    def mark_deleted(self, url):
        with self.connect() as db:
            # A disappearing redirect must not delete its live target.
            db.execute("UPDATE articles SET deleted=1 WHERE url=?", (url,))
            db.execute("DELETE FROM aliases WHERE url=?", (url,))

    def article(self, article_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM articles WHERE id=?", (article_id,)).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        data["blocks"] = [Block(**b) for b in data["blocks"]]
        return Article(**data)

    def dirty_articles(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,deleted,digest FROM articles WHERE digest!=indexed_digest OR deleted=1"
                )
            ]

    def chunks(self, ids):
        if not ids:
            return []
        with self.connect() as db:
            rows = db.execute(
                f"""SELECT c.*,a.title FROM chunks c JOIN articles a ON a.id=c.article_id
                WHERE c.id IN ({",".join("?" for _ in ids)}) AND a.deleted=0 AND c.digest=a.digest""",
                ids,
            )
            result = {r["id"]: dict(r) for r in rows}
        return [result[i] for i in ids if i in result]

    def keyword(self, query, limit=20):
        import re

        words = re.findall(r"[\w]+", query)[:40]
        stop = {"what", "how", "the", "is", "a", "an", "to", "of", "do", "i", "for", "and", "it"}
        words = [w for w in words if w.lower() not in stop] or words
        if not words:
            return []
        expression = " OR ".join('"' + w + '"' for w in words)
        with self.connect() as db:
            return [
                r[0]
                for r in db.execute(
                    """SELECT id FROM chunks_fts WHERE chunks_fts MATCH ?
                ORDER BY bm25(chunks_fts,0,5,2,1) LIMIT ?""",
                    (expression, limit),
                )
            ]

    def stats(self):
        with self.connect() as db:
            result = {
                key: db.execute(sql).fetchone()[0]
                for key, sql in {
                    "articles": "SELECT count(*) FROM articles WHERE deleted=0",
                    "chunks": "SELECT count(*) FROM chunks c JOIN articles a ON a.id=c.article_id WHERE a.deleted=0 AND c.digest=a.digest",
                    "indexed_articles": "SELECT count(*) FROM articles WHERE deleted=0 AND indexed_digest=digest",
                    "pending": "SELECT count(*) FROM frontier WHERE state='pending'",
                    "errors": "SELECT count(*) FROM frontier WHERE state='error'",
                    "done": "SELECT count(*) FROM frontier WHERE state='done'",
                }.items()
            }
            return result

    def errors(self):
        with self.connect() as db:
            return [
                dict(r) for r in db.execute("SELECT url,error FROM frontier WHERE state='error' LIMIT 100")
            ]

    def set(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def record_usage(self, payload):
        with self.connect() as db:
            db.execute("INSERT INTO usage(created,payload) VALUES (?,?)", (now(), json.dumps(payload)))
