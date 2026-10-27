"""Local SQLite repository: one short-lived connection per operation."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        for directory in ("uploads", "results", "snapshots", "previews"):
            (root / directory).mkdir(exist_ok=True)
        with self.connect() as db:
            for table in ("videos", "events", "configurations", "notifications"):
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} "
                    "(id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "orel.sqlite3", timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def put(self, table: str, key: str, value: dict):
        self._table(table)
        with self.connect() as db:
            db.execute(
                f"INSERT INTO {table} VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def get(self, table: str, key: str) -> dict | None:
        self._table(table)
        with self.connect() as db:
            row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, table: str) -> list[dict]:
        self._table(table)
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(f"SELECT payload FROM {table} ORDER BY rowid DESC")
            ]

    @staticmethod
    def _table(table: str):
        if table not in {"videos", "events", "configurations", "notifications"}:
            raise ValueError("Unknown table")
