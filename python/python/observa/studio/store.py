"""Small durable application store; canonical economics stay in run artifacts."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path


def new_id() -> str:
    return uuid.uuid4().hex


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / "studio.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS records (
              kind TEXT NOT NULL, id TEXT NOT NULL, parent TEXT,
              data TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
              PRIMARY KEY(kind,id));
            CREATE INDEX IF NOT EXISTS record_parent ON records(kind,parent);
            CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL,
              type TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_conversation ON events(conversation,seq);
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
              conversation UNINDEXED, item UNINDEXED, text);
            PRAGMA user_version=1;
        """)
        self.db.commit()

    def put(self, kind: str, value: dict, parent: str | None = None) -> dict:
        now = time.time()
        value = dict(value)
        value.setdefault("id", new_id())
        old = self.get(kind, value["id"])
        value.setdefault("created", old["created"] if old else now)
        value["updated"] = now
        with self.db:
            self.db.execute(
                "INSERT INTO records VALUES(?,?,?,?,?,?) ON CONFLICT(kind,id) "
                "DO UPDATE SET data=excluded.data,updated=excluded.updated",
                (kind, value["id"], parent, encoded(value), value["created"], now),
            )
            if kind == "item" and value.get("type") in ("user", "agentMessage"):
                self.db.execute("DELETE FROM search WHERE item=?", (value["id"],))
                self.db.execute("INSERT INTO search VALUES(?,?,?)",
                                (parent, value["id"], value.get("text", "")))
        return value

    def get(self, kind: str, identifier: str) -> dict | None:
        row = self.db.execute("SELECT data FROM records WHERE kind=? AND id=?",
                              (kind, identifier)).fetchone()
        return json.loads(row[0]) if row else None

    def require(self, kind: str, identifier: str) -> dict:
        value = self.get(kind, identifier)
        if value is None:
            raise KeyError(f"{kind} not found")
        return value

    def list(self, kind: str, parent: str | None = None) -> list[dict]:
        query = "SELECT data FROM records WHERE kind=?"
        args = [kind]
        if parent is not None:
            query += " AND parent=?"
            args.append(parent)
        query += " ORDER BY created"
        return [json.loads(row[0]) for row in self.db.execute(query, args)]

    def emit(self, conversation: str, kind: str, data: dict) -> int:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO events(conversation,type,data) VALUES(?,?,?)",
                (conversation, kind, encoded(data)),
            )
        return cursor.lastrowid

    def events(self, conversation: str, after: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT seq,type,data FROM events WHERE conversation=? AND seq>? ORDER BY seq LIMIT 500",
            (conversation, after),
        )
        return [dict(seq=r[0], type=r[1], data=json.loads(r[2])) for r in rows]

    def interrupt_activity(self, conversation: str):
        """Settle presentation state when no provider can finish these items."""
        for kind, pending, finished in (("item", "running", "interrupted"),
                                        ("approval", "pending", "expired")):
            for value in self.list(kind, conversation):
                if value.get("status") == pending:
                    value = self.put(kind, {**value, "status": finished}, conversation)
                    self.emit(conversation, kind, value)

    def search(self, query: str) -> list[str]:
        # Treat input as literal words, never as FTS syntax.
        terms = ['"' + word.replace('"', '""') + '"' for word in query.split()[:20]]
        if not terms:
            return []
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT conversation FROM search WHERE search MATCH ? LIMIT 100",
            (" AND ".join(terms),))]

    def close(self):
        self.db.close()
