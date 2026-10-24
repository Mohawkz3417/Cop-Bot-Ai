"""
Shared pytest fixtures.

Each test gets an isolated SQLite database (a fresh temp file + a fresh
thread-local connection registry) so tests never see each other's sessions,
messages, feedback or filed complaints — and rate limiting is disabled so
a big test run never trips the very safety net we're testing elsewhere.
"""
import threading

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend import database
    from backend.config import settings
    from backend.main import app

    db_path = tmp_path / "test_copbot.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(database, "_local", threading.local())
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    with TestClient(app) as test_client:
        yield test_client


def parse_sse(text: str) -> list[dict]:
    """Turn a raw `text/event-stream` body into a list of parsed JSON events."""
    import json

    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block.startswith("data:"):
            continue
        payload = block[len("data:"):].strip()
        if payload:
            events.append(json.loads(payload))
    return events
