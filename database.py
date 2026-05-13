"""
database.py — SQLite persistence layer.

Tables
------
announcements  : every announcement ever seen (de-duplicated by hash)
fo_stocks      : cached F&O stock universe (refreshed each run)
"""

import sqlite3
import contextlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import config
from utils import setup_logger

log = setup_logger("database")


# ─── Connection helper ────────────────────────────────────────────────────────

@contextlib.contextmanager
def get_conn():
    """Yield a SQLite connection with WAL mode and foreign-key support."""
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    NOT NULL UNIQUE,
    exchange        TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    company_name    TEXT,
    headline        TEXT    NOT NULL,
    category        TEXT    NOT NULL DEFAULT 'Miscellaneous',
    impact_score    INTEGER NOT NULL DEFAULT 3,
    impact_label    TEXT    NOT NULL DEFAULT '🟢 Low',
    attachment_url  TEXT,
    ann_datetime    TEXT,
    fetched_at      TEXT    NOT NULL,
    alerted         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ann_hash     ON announcements (hash);
CREATE INDEX IF NOT EXISTS idx_ann_symbol   ON announcements (symbol);
CREATE INDEX IF NOT EXISTS idx_ann_category ON announcements (category);
CREATE INDEX IF NOT EXISTS idx_ann_alerted  ON announcements (alerted);

CREATE TABLE IF NOT EXISTS fo_stocks (
    symbol  TEXT PRIMARY KEY,
    name    TEXT,
    source  TEXT,
    updated TEXT
);
"""


def init_db() -> None:
    """Create tables and indexes if they don't exist yet."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    log.info("Database initialised at '%s'.", config.DB_PATH)


# ─── F&O stock cache ──────────────────────────────────────────────────────────

def upsert_fo_stocks(stocks: List[Dict]) -> int:
    """
    Replace the fo_stocks table with a fresh list.
    Each dict must have 'symbol' and optionally 'name', 'source'.
    Returns number of rows inserted.
    """
    if not stocks:
        return 0
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        (s["symbol"].upper(), s.get("name", ""), s.get("source", ""), now)
        for s in stocks
    ]
    with get_conn() as conn:
        conn.execute("DELETE FROM fo_stocks;")
        conn.executemany(
            "INSERT OR REPLACE INTO fo_stocks (symbol, name, source, updated) "
            "VALUES (?,?,?,?);",
            rows,
        )
    log.info("F&O stock universe updated: %d symbols.", len(rows))
    return len(rows)


def get_fo_symbols() -> set:
    """Return the set of F&O symbols from the local cache."""
    with get_conn() as conn:
        rows = conn.execute("SELECT symbol FROM fo_stocks;").fetchall()
    return {r["symbol"] for r in rows}


# ─── Announcement storage ────────────────────────────────────────────────────

def is_seen(hash_val: str) -> bool:
    """Return True if this hash already exists in the DB."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM announcements WHERE hash=?;", (hash_val,)
        ).fetchone()
    return row is not None


def bulk_is_seen(hashes: List[str]) -> set:
    """Return the subset of hashes already present in the DB."""
    if not hashes:
        return set()
    placeholders = ",".join("?" * len(hashes))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT hash FROM announcements WHERE hash IN ({placeholders});",
            hashes,
        ).fetchall()
    return {r["hash"] for r in rows}


def insert_announcements(announcements: List[Dict]) -> List[Dict]:
    """
    Insert a batch of new announcements, skipping duplicates.
    Returns the list that was actually inserted (new ones only).
    """
    if not announcements:
        return []

    hashes   = [a["hash"] for a in announcements]
    seen_set = bulk_is_seen(hashes)
    new_anns = [a for a in announcements if a["hash"] not in seen_set]

    if not new_anns:
        log.info("No new announcements to insert (all duplicates).")
        return []

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        (
            a["hash"], a["exchange"], a["symbol"],
            a.get("company_name", ""), a["headline"],
            a["category"], a["impact_score"], a["impact_label"],
            a.get("attachment_url", ""), a.get("ann_datetime", ""),
            now, 0,
        )
        for a in new_anns
    ]

    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO announcements
            (hash, exchange, symbol, company_name, headline,
             category, impact_score, impact_label,
             attachment_url, ann_datetime, fetched_at, alerted)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?);
            """,
            rows,
        )

    log.info("Inserted %d new announcements.", len(new_anns))
    return new_anns


def mark_alerted(hash_val: str) -> None:
    """Mark a single announcement as having been alerted."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE announcements SET alerted=1 WHERE hash=?;", (hash_val,)
        )


def get_unalerted() -> List[Dict]:
    """Fetch all announcements not yet sent to Telegram."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM announcements WHERE alerted=0 ORDER BY id ASC;"
        ).fetchall()
    return [dict(r) for r in rows]


def recent_stats(hours: int = 24) -> Dict:
    """Return summary stats for the last N hours (for logging/dashboard)."""
    since = (datetime.utcnow() - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM announcements WHERE fetched_at >= ?;", (since,)
        ).fetchone()[0]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) AS cnt FROM announcements "
            "WHERE fetched_at >= ? GROUP BY category ORDER BY cnt DESC;",
            (since,),
        ).fetchall()
    return {"total": total, "by_category": [dict(r) for r in by_cat]}
