"""SQLite persistence (PRD §52).

Deliberately small. It stores what the evaluation chapter needs — the debate
transcripts, timings and feedback — and nothing that identifies a person. Raw
queries are stored because the experiment log needs them; there is a single
switch below to turn that off (PRD §67).
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .config import settings

STORE_RAW_QUERIES = True
DB_PATH: Path = settings.data_processed / "debaterec.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    query        TEXT,
    domain       TEXT,
    method       TEXT,
    mode         TEXT,
    total_seconds REAL,
    llm_calls    INTEGER,
    metrics_json TEXT,
    created_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS debates (
    debate_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   INTEGER,
    item_id      TEXT NOT NULL,
    domain       TEXT,
    rank         INTEGER,
    final_score  REAL,
    confidence   REAL,
    decision     TEXT,
    supporter_json TEXT,
    critic_json    TEXT,
    judge_json     TEXT,
    created_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
    interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    item_id      TEXT NOT NULL,
    domain       TEXT,
    action       TEXT NOT NULL,
    comment      TEXT,
    created_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    preference_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    domain       TEXT,
    facet        TEXT,
    value        TEXT,
    weight       REAL,
    source       TEXT,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interactions_session ON interactions(session_id);
CREATE INDEX IF NOT EXISTS idx_prefs_session ON preferences(session_id, domain);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def log_request(session_id: str, query: str, payload: dict) -> int:
    metrics = payload.get("metrics", {})
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO requests (session_id, query, domain, method, mode, total_seconds,"
            " llm_calls, metrics_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                query if STORE_RAW_QUERIES else None,
                payload.get("domain"),
                payload.get("method"),
                payload.get("mode"),
                metrics.get("total_seconds"),
                metrics.get("llm_calls", 0),
                json.dumps(metrics),
                time.time(),
            ),
        )
        request_id = int(cur.lastrowid)
        for card in payload.get("results", []):
            debate = card.get("debate", {})
            conn.execute(
                "INSERT INTO debates (request_id, item_id, domain, rank, final_score, confidence,"
                " decision, supporter_json, critic_json, judge_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id, card.get("item_id"), card.get("domain"), card.get("rank"),
                    card.get("score"), card.get("confidence"), card.get("decision"),
                    json.dumps(debate.get("supporter", {})),
                    json.dumps(debate.get("critic", {})),
                    json.dumps(debate.get("judge", {})),
                    time.time(),
                ),
            )
    return request_id


def log_feedback(session_id: str, item_id: str, domain: str, action: str, comment: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO interactions (session_id, item_id, domain, action, comment, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (session_id, item_id, domain, action, comment, time.time()),
        )


def save_preference(session_id: str, domain: str, facet: str, value: str, weight: float, source: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO preferences (session_id, domain, facet, value, weight, source, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (session_id, domain, facet, value, weight, source, time.time()),
        )


def session_memory(session_id: str, domain: str) -> list[dict]:
    """Lightweight preference memory (PRD §26)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT facet, value, weight, source FROM preferences"
            " WHERE session_id = ? AND domain = ? ORDER BY created_at DESC LIMIT 24",
            (session_id, domain),
        ).fetchall()
    return [dict(r) for r in rows]


def blocked_items(session_id: str) -> set[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT item_id FROM interactions WHERE session_id = ? AND action = 'blocked'",
            (session_id,),
        ).fetchall()
    return {r["item_id"] for r in rows}


def stats() -> dict:
    with connect() as conn:
        def one(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0] or 0)

        return {
            "requests": one("SELECT COUNT(*) FROM requests"),
            "debates": one("SELECT COUNT(*) FROM debates"),
            "feedback": one("SELECT COUNT(*) FROM interactions"),
            "avg_seconds": round(
                float(conn.execute("SELECT AVG(total_seconds) FROM requests").fetchone()[0] or 0), 3
            ),
        }
