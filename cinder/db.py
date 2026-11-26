"""SQLite schema and queries."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
  id INTEGER PRIMARY KEY,               -- GitHub repo id
  full_name TEXT NOT NULL UNIQUE,
  description TEXT,
  default_branch TEXT,
  pushed_at TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  fork INTEGER NOT NULL DEFAULT 0,
  private INTEGER NOT NULL DEFAULT 0,
  excluded INTEGER NOT NULL DEFAULT 0,
  excluded_set INTEGER NOT NULL DEFAULT 0, -- user changed the toggle
  digest TEXT,
  digest_pushed_at TEXT,
  synced_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                    -- daily | manual
  status TEXT NOT NULL,                  -- running | succeeded | failed
  step TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  cost_usd REAL NOT NULL DEFAULT 0,
  new_cards INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  local_date TEXT                        -- date in the configured zone
);
CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  kind TEXT NOT NULL,                    -- feature | project
  repo TEXT,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  value INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending', -- pending | liked | dismissed
  created_at TEXT NOT NULL,
  decided_at TEXT,
  note TEXT,
  never INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS cards_status ON cards(status, value DESC);
CREATE TABLE IF NOT EXISTS specs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id INTEGER NOT NULL UNIQUE REFERENCES cards(id),
  status TEXT NOT NULL,                  -- queued | writing | pr_open | failed
  pr_url TEXT,
  error TEXT,
  cost_usd REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  markdown TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  swipes_through TEXT NOT NULL DEFAULT ''  -- decided_at of the last swipe folded in
);
CREATE TABLE IF NOT EXISTS never_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  card_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "tz": "America/Chicago",
    "ready_by": "07:00",
    "generate_lead_minutes": 120,
    "deck_size": 10,
    "mix_features": 7,
    "mix_projects": 3,
    "max_repos": 25,
    "budget_ideation": 5.0,
    "budget_profile": 0.5,
    "budget_spec": 3.0,
    "budget_never_rule": 0.2,
    "demo_mode": False,
}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "idea"


class DB:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        with self.connect() as c:
            row = c.execute(sql, args).fetchone()
            return dict(row) if row else None

    def run(self, sql: str, args: tuple = ()) -> int:
        with self.connect() as c:
            cur = c.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # ---- settings ----
    def settings(self) -> dict[str, Any]:
        out = dict(DEFAULT_SETTINGS)
        for row in self.all("SELECT key, value FROM settings"):
            out[row["key"]] = json.loads(row["value"])
        return out

    def set_settings(self, values: dict[str, Any]) -> None:
        with self.tx() as c:
            for k, v in values.items():
                c.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, json.dumps(v)),
                )

    # ---- cards ----
    @staticmethod
    def card_out(row: dict) -> dict:
        payload = json.loads(row["payload_json"])
        out = {k: v for k, v in row.items() if k not in ("payload_json", "value", "never")}
        out["never"] = bool(row["never"])
        out.update({k: v for k, v in payload.items() if k not in ("value", "kind", "repo", "title")})
        return out

    def deck(self) -> list[dict]:
        rows = self.all("SELECT * FROM cards WHERE status='pending' ORDER BY value DESC, id")
        return [self.card_out(r) for r in rows]

    def add_card(self, c: sqlite3.Connection, run_id: int | None, card: dict) -> int:
        title = card["title"].strip()[:120]
        base = slugify(title)
        slug, n = base, 2
        while c.execute("SELECT 1 FROM cards WHERE slug=?", (slug,)).fetchone():
            slug, n = f"{base}-{n}", n + 1
        payload = {k: v for k, v in card.items()}
        cur = c.execute(
            "INSERT INTO cards(run_id, kind, repo, slug, title, payload_json, value, created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                run_id,
                card["kind"],
                card.get("repo") if card["kind"] == "feature" else None,
                slug,
                title,
                json.dumps(payload),
                int(card.get("value", 0)),
                now(),
            ),
        )
        return cur.lastrowid

    def card(self, card_id: int) -> dict | None:
        row = self.one("SELECT * FROM cards WHERE id=?", (card_id,))
        return row

    def card_payload(self, card_id: int) -> dict:
        row = self.card(card_id)
        return json.loads(row["payload_json"]) if row else {}

    # ---- profile ----
    def profile(self) -> dict:
        return self.one("SELECT * FROM profile WHERE id=1") or {
            "markdown": "",
            "updated_at": None,
            "swipes_through": "",
        }

    def set_profile(self, markdown: str, through: str) -> None:
        self.run(
            "INSERT INTO profile(id, markdown, updated_at, swipes_through) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET markdown=excluded.markdown, updated_at=excluded.updated_at, "
            "swipes_through=excluded.swipes_through",
            (markdown, now(), through),
        )
