"""
Persistence layer for CopBot AI, built on stdlib sqlite3 (zero extra
dependency, zero setup — the .db file is created automatically on first
run). Covers four things:

  1. sessions / messages  -> chat history, resumable from the sidebar.
  2. feedback              -> 👍 / 👎 rating per assistant message, so the
                               bot's answer quality can be measured over time.
  3. filed_complaints       -> complaints created through the "File a
                               Complaint" feature (separate from the
                               read-only bundled `complaint_records.json`
                               dataset used for the "Track a Complaint"
                               demo lookup).
  4. stats helpers          -> aggregate queries that power /api/stats and
                               the admin analytics dashboard.
"""
from __future__ import annotations

import random
import sqlite3
import string
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from backend.config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'New chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    sources TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    rating INTEGER NOT NULL,           -- 1 = thumbs up, -1 = thumbs down
    comment TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS filed_complaints (
    complaint_id TEXT PRIMARY KEY,
    session_id TEXT,
    complainant_name TEXT,
    contact TEXT,
    crime_type TEXT NOT NULL,
    description TEXT,
    location TEXT,
    status TEXT NOT NULL DEFAULT 'Registered',
    created_at TEXT NOT NULL
);
"""


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def init_db() -> None:
    conn = _get_conn()
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def _cursor():
    conn = _get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    finally:
        cur.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(title: str = "New chat") -> dict:
    session_id = str(uuid.uuid4())
    now = _now()
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )
    return {"id": session_id, "title": title, "created_at": now, "updated_at": now}


def ensure_session(session_id: str | None) -> str:
    if session_id:
        with _cursor() as cur:
            cur.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
            if cur.fetchone():
                return session_id
    return create_session()["id"]


def touch_session(session_id: str, title: str | None = None) -> None:
    with _cursor() as cur:
        if title:
            cur.execute(
                "UPDATE sessions SET updated_at = ?, title = ? WHERE id = ?",
                (_now(), title, session_id),
            )
        else:
            cur.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))


def list_sessions(limit: int = 50) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, title, created_at, updated_at FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def delete_session(session_id: str) -> None:
    with _cursor() as cur:
        cur.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def add_message(session_id: str, role: str, content: str,
                 provider: str | None = None, model: str | None = None,
                 sources: str | None = None) -> int:
    """Returns the new message's row id (used to attach feedback to it)."""
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO messages (session_id, role, content, provider, model, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, content, provider, model, sources, _now()),
        )
        return cur.lastrowid


def get_messages(session_id: str) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, role, content, provider, model, sources, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def maybe_autotitle(session_id: str, first_user_message: str) -> None:
    title = first_user_message.strip().replace("\n", " ")
    if len(title) > 48:
        title = title[:45].rstrip() + "..."
    touch_session(session_id, title=title or "New chat")


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def add_feedback(message_id: int, rating: int, comment: str | None = None) -> dict:
    if rating not in (1, -1):
        raise ValueError("rating must be 1 or -1")
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO feedback (message_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
            (message_id, rating, comment, _now()),
        )
    return {"message_id": message_id, "rating": rating}


def feedback_summary() -> dict:
    with _cursor() as cur:
        cur.execute(
            "SELECT SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS up, "
            "SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) AS down, "
            "COUNT(*) AS total FROM feedback"
        )
        row = cur.fetchone()
        return {"up": row["up"] or 0, "down": row["down"] or 0, "total": row["total"] or 0}


# ---------------------------------------------------------------------------
# Filed complaints (interactive "File a Complaint" feature)
# ---------------------------------------------------------------------------

def _generate_complaint_id() -> str:
    suffix = "".join(random.choices(string.digits, k=6))
    return f"CB{suffix}"


def file_complaint(crime_type: str, description: str = "", location: str = "",
                    complainant_name: str = "", contact: str = "",
                    session_id: str | None = None) -> dict:
    complaint_id = _generate_complaint_id()
    now = _now()
    with _cursor() as cur:
        # extremely unlikely collision guard
        cur.execute("SELECT 1 FROM filed_complaints WHERE complaint_id = ?", (complaint_id,))
        while cur.fetchone():
            complaint_id = _generate_complaint_id()
            cur.execute("SELECT 1 FROM filed_complaints WHERE complaint_id = ?", (complaint_id,))
        cur.execute(
            "INSERT INTO filed_complaints "
            "(complaint_id, session_id, complainant_name, contact, crime_type, description, "
            "location, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (complaint_id, session_id, complainant_name, contact, crime_type,
             description, location, "Registered", now),
        )
    return {
        "complaint_id": complaint_id,
        "crime_type": crime_type,
        "description": description,
        "location": location,
        "status": "Registered",
        "date_reported": now,
    }


def find_filed_complaint(complaint_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT complaint_id, crime_type, description, location, status, created_at "
            "FROM filed_complaints WHERE complaint_id = ?",
            (complaint_id.strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def recent_filed_complaints(limit: int = 10) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT complaint_id, crime_type, status, created_at FROM filed_complaints "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Aggregate stats (admin dashboard)
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    with _cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM sessions")
        total_sessions = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM messages")
        total_messages = cur.fetchone()["c"]

        cur.execute(
            "SELECT COALESCE(provider,'unset') AS provider, COUNT(*) AS c FROM messages "
            "WHERE role = 'assistant' GROUP BY provider ORDER BY c DESC"
        )
        provider_split = [dict(row) for row in cur.fetchall()]

        cur.execute(
            "SELECT DATE(created_at) AS day, COUNT(*) AS c FROM messages "
            "WHERE role = 'user' GROUP BY day ORDER BY day DESC LIMIT 14"
        )
        messages_by_day = [dict(row) for row in cur.fetchall()][::-1]

        cur.execute("SELECT COUNT(*) AS c FROM filed_complaints")
        total_filed_complaints = cur.fetchone()["c"]

        cur.execute(
            "SELECT crime_type, COUNT(*) AS c FROM filed_complaints "
            "GROUP BY crime_type ORDER BY c DESC LIMIT 6"
        )
        complaints_by_type = [dict(row) for row in cur.fetchall()]

    return {
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "provider_split": provider_split,
        "messages_by_day": messages_by_day,
        "total_filed_complaints": total_filed_complaints,
        "complaints_by_type": complaints_by_type,
        "feedback": feedback_summary(),
    }
