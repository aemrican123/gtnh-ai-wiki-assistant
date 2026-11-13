"""Portable logical backups, including cached local vectors, without keys or logs."""

import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from filelock import FileLock

from .store import Store, now


def backup(store, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(store.directory / "writer.lock"), timeout=0):
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / "knowledge.sqlite3"
            with store.connect() as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
                target.execute("UPDATE articles SET indexed_digest=''")
                target.commit()
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "knowledge.sqlite3")
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "format": 1,
                            "created": now(),
                            "embedding_model": store.get("embedding_model"),
                            "note": "Raw HTML and embedding cache included. Rebuild Chroma after restoration.",
                        }
                    ),
                )
    return destination


def restore(archive_path, destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Restore destination must be empty; existing data is never overwritten")
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != 1:
            raise ValueError("Unsupported backup format")
        # Explicit member reads avoid path traversal through ZIP names.
        payload = archive.read("knowledge.sqlite3")
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "knowledge.sqlite3"
    path.write_bytes(payload)
    with closing(sqlite3.connect(path)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup database failed its integrity check")
        db.execute("UPDATE articles SET indexed_digest=''")
        db.commit()
    return Store(destination)
