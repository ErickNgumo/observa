"""Ordered, backed-up application migrations; never touch canonical run files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import uuid

VERSION = 2


def _initial(db):
    for statement in (
        "CREATE TABLE records (kind TEXT NOT NULL, id TEXT NOT NULL, parent TEXT, "
        "data TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, PRIMARY KEY(kind,id))",
        "CREATE INDEX record_parent ON records(kind,parent)",
        "CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL, "
        "type TEXT NOT NULL, data TEXT NOT NULL)",
        "CREATE INDEX event_conversation ON events(conversation,seq)",
        "CREATE VIRTUAL TABLE search USING fts5(conversation UNINDEXED, item UNINDEXED, text)",
    ):
        db.execute(statement)


def _providers(db):
    for row in db.execute("SELECT id,data FROM records WHERE kind='conversation'").fetchall():
        value = json.loads(row[1])
        if not value.get("provider"):
            value["provider"] = "codex"
            db.execute("UPDATE records SET data=? WHERE kind='conversation' AND id=?",
                       (json.dumps(value, ensure_ascii=False, allow_nan=False), row[0]))


MIGRATIONS = {1: _initial, 2: _providers}


def migrate(db: sqlite3.Connection, root: Path):
    current = db.execute("PRAGMA user_version").fetchone()[0]
    if current > VERSION:
        raise RuntimeError(f"Studio data requires schema {current}; this application supports {VERSION}. "
                           "Open it with a newer Studio version.")
    if current == VERSION:
        return
    if current == 0 and db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
        raise RuntimeError("Unversioned Studio database is not empty; refusing to overwrite it.")
    if current:
        directory = root / "backups"
        directory.mkdir(mode=0o700, exist_ok=True)
        backup = directory / f"studio-v{current}-{uuid.uuid4().hex}.sqlite3"
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        destination = sqlite3.connect(backup)
        try:
            db.backup(destination)
        finally:
            destination.close()
    # Explicit BEGIN is needed for transactional DDL. executescript commits
    # pending transactions, so migrations use execute throughout.
    db.execute("BEGIN IMMEDIATE")
    try:
        for version in range(current + 1, VERSION + 1):
            MIGRATIONS[version](db)
            db.execute(f"PRAGMA user_version={version}")
        db.commit()
    except BaseException:
        db.rollback()
        raise
