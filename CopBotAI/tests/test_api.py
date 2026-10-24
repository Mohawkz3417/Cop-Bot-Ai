from tests.conftest import parse_sse


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "groq" in data["providers"]
    assert "ollama" in data["providers"]
    assert data["knowledge_base_docs"] > 0


def test_config(client):
    res = client.get("/api/config")
    assert res.status_code == 200
    assert "default_provider" in res.json()


def test_session_lifecycle(client):
    res = client.post("/api/sessions")
    assert res.status_code == 200
    session = res.json()
    assert session["id"]

    res = client.get("/api/sessions")
    assert res.status_code == 200
    assert any(s["id"] == session["id"] for s in res.json())

    res = client.delete(f"/api/sessions/{session['id']}")
    assert res.status_code == 200


def test_chat_stream_offline_direct_hit(client):
    """A high-confidence FAQ match should answer instantly from the
    knowledge base without needing any LLM provider configured."""
    res = client.post("/api/chat/stream", json={
        "message": "What are the emergency helpline numbers in Chennai?",
        "provider": "rag_only",
    })
    assert res.status_code == 200
    events = parse_sse(res.text)
    types = [e["type"] for e in events]

    assert "session" in types
    assert "sources" in types
    assert "meta" in types
    assert "chunk" in types
    assert "done" in types

    done_event = [e for e in events if e["type"] == "done"][0]
    assert done_event["provider"] == "rag"
    assert done_event["message_id"] is not None

    meta_event = [e for e in events if e["type"] == "meta"][0]
    assert meta_event["provider"] == "rag"

    full_text = "".join(e["content"] for e in events if e["type"] == "chunk")
    assert len(full_text.strip()) > 0


def test_chat_stream_requires_nonempty_message(client):
    res = client.post("/api/chat/stream", json={"message": "   ", "provider": "rag_only"})
    assert res.status_code == 400


def test_chat_stream_rejects_overlong_message(client):
    # 5000 chars exceeds both the Pydantic schema cap (4000) and the
    # runtime MAX_MESSAGE_LENGTH check (2000) — either layer rejecting it
    # (422 from validation, 400 from the handler) is correct.
    res = client.post("/api/chat/stream", json={
        "message": "x" * 5000,
        "provider": "rag_only",
    })
    assert res.status_code in (400, 422)


def test_chat_stream_persists_history(client):
    payload = {"message": "How do I file an FIR for theft?", "provider": "rag_only"}
    res = client.post("/api/chat/stream", json=payload)
    events = parse_sse(res.text)
    session_id = [e for e in events if e["type"] == "session"][0]["session_id"]

    res = client.get(f"/api/sessions/{session_id}/messages")
    assert res.status_code == 200
    messages = res.json()
    assert len(messages) == 2  # user + assistant
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_emergency_detection_banner_event(client):
    res = client.post("/api/chat/stream", json={
        "message": "help me I am being attacked right now",
        "provider": "rag_only",
    })
    events = parse_sse(res.text)
    assert any(e["type"] == "emergency" for e in events)


def test_feedback_round_trip(client):
    res = client.post("/api/chat/stream", json={
        "message": "What are the emergency helpline numbers in Chennai?",
        "provider": "rag_only",
    })
    events = parse_sse(res.text)
    message_id = [e for e in events if e["type"] == "done"][0]["message_id"]

    res = client.post("/api/feedback", json={"message_id": message_id, "rating": 1})
    assert res.status_code == 200

    res = client.get("/api/stats")
    assert res.json()["feedback"]["up"] >= 1


def test_feedback_rejects_zero_rating(client):
    res = client.post("/api/feedback", json={"message_id": 1, "rating": 0})
    assert res.status_code == 400


def test_stations_search(client):
    res = client.get("/api/stations", params={"q": "Teynampet"})
    assert res.status_code == 200
    stations = res.json()
    assert len(stations) >= 1
    assert "Teynampet" in stations[0]["name"]


def test_legal_search(client):
    res = client.get("/api/legal/search", params={"q": "murder punishment"})
    assert res.status_code == 200
    hits = res.json()
    assert hits
    assert "302" in hits[0]["section"]


def test_legal_search_requires_query(client):
    res = client.get("/api/legal/search", params={"q": ""})
    assert res.status_code == 400


def test_emergency_directory(client):
    res = client.get("/api/emergency")
    assert res.status_code == 200
    assert len(res.json()) == 20


def test_complaint_lookup_known_sample(client):
    res = client.post("/api/complaint/lookup", json={"complaint_id": "410932"})
    assert res.status_code == 200
    assert res.json()["complaint_id"] == "410932"


def test_complaint_lookup_unknown(client):
    res = client.post("/api/complaint/lookup", json={"complaint_id": "does-not-exist"})
    assert res.status_code == 404


def test_file_and_lookup_new_complaint(client):
    res = client.post("/api/complaint/file", json={
        "crime_type": "Cybercrime",
        "description": "Phishing email received",
        "location": "T Nagar, Chennai",
    })
    assert res.status_code == 200
    filed = res.json()
    assert filed["complaint_id"].startswith("CB")
    assert filed["status"] == "Registered"

    res = client.post("/api/complaint/lookup", json={"complaint_id": filed["complaint_id"]})
    assert res.status_code == 200
    assert res.json()["crime_type"] == "Cybercrime"


def test_stats_shape(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    for key in ("total_sessions", "total_messages", "provider_split",
                "messages_by_day", "total_filed_complaints",
                "complaints_by_type", "feedback"):
        assert key in data


def test_rate_limiting_blocks_after_threshold(client, monkeypatch):
    from backend.config import settings
    from backend.rate_limit import chat_limiter

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_MAX_REQUESTS", 2)
    chat_limiter.max_requests = 2
    chat_limiter._hits.clear()

    payload = {"message": "What is the emergency number?", "provider": "rag_only"}
    r1 = client.post("/api/chat/stream", json=payload)
    r2 = client.post("/api/chat/stream", json=payload)
    r3 = client.post("/api/chat/stream", json=payload)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429


def test_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "CopBot AI" in res.text


def test_admin_dashboard_is_served(client):
    res = client.get("/admin.html")
    assert res.status_code == 200
    assert "Analytics" in res.text
