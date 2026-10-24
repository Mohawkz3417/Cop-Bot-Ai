"""
CopBot AI — FastAPI backend.

One process serves both the JSON/SSE API and the static frontend, so the
whole project is a single `pip install -r requirements.txt && python -m backend.main`
away from running end to end.

Endpoint map (also see README.md#api-reference and /docs for live Swagger UI):
  GET  /api/health                    provider connectivity + KB stats
  GET  /api/config                    public runtime config for the frontend
  GET  /api/stats                     aggregate usage stats (admin dashboard)
  GET  /api/sessions                  list chat sessions
  POST /api/sessions                  create a new chat session
  GET  /api/sessions/{id}/messages     full history for a session
  DELETE /api/sessions/{id}            delete a session
  POST /api/chat/stream                SSE streaming chat (the core feature)
  POST /api/feedback                   👍 / 👎 a specific assistant message
  GET  /api/emergency                  emergency helpline directory
  GET  /api/stations?q=                search Chennai police stations
  GET  /api/legal/search?q=            search IPC sections
  POST /api/complaint/lookup           look up a complaint by ID
  POST /api/complaint/file             file a new complaint (demo feature)
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend import database
from backend.config import BASE_DIR, settings
from backend.data_loader import find_complaint
from backend.llm_service import check_groq, check_ollama, generate_reply
from backend.models import (
    ChatRequest,
    ComplaintFileRequest,
    ComplaintLookupRequest,
    FeedbackRequest,
)
from backend.rag_engine import rag_engine
from backend.rate_limit import enforce_rate_limit

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("copbot.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    rag_engine.build()
    logger.info("%s v%s ready. %d knowledge-base documents indexed.",
                settings.APP_NAME, settings.APP_VERSION, len(rag_engine.documents))
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered virtual assistant for police & public-safety queries, "
                 "grounded in a real FAQ/IPC/station/emergency knowledge base, with "
                 "an interchangeable Groq / Ollama LLM pipeline.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health / config / stats
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["system"])
def health():
    groq = check_groq()
    ollama = check_ollama()
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "providers": {"groq": groq, "ollama": ollama},
        "default_provider": settings.DEFAULT_PROVIDER,
        "knowledge_base_docs": len(rag_engine.documents),
    }


@app.get("/api/config", tags=["system"])
def get_config():
    return {
        "default_provider": settings.DEFAULT_PROVIDER,
        "groq_model": settings.GROQ_MODEL,
        "ollama_model": settings.OLLAMA_MODEL,
        "max_message_length": settings.MAX_MESSAGE_LENGTH,
        "rate_limit": {
            "enabled": settings.RATE_LIMIT_ENABLED,
            "max_requests": settings.RATE_LIMIT_MAX_REQUESTS,
            "window_seconds": settings.RATE_LIMIT_WINDOW_SECONDS,
        },
    }


@app.get("/api/stats", tags=["system"])
def stats():
    """Aggregate usage stats consumed by the /admin.html analytics dashboard."""
    return database.get_stats()


# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------

@app.get("/api/sessions", tags=["chat"])
def get_sessions():
    return database.list_sessions()


@app.post("/api/sessions", tags=["chat"])
def new_session():
    return database.create_session()


@app.get("/api/sessions/{session_id}/messages", tags=["chat"])
def session_messages(session_id: str):
    return database.get_messages(session_id)


@app.delete("/api/sessions/{session_id}", tags=["chat"])
def remove_session(session_id: str):
    database.delete_session(session_id)
    return {"deleted": session_id}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@app.post("/api/feedback", tags=["chat"])
def submit_feedback(req: FeedbackRequest):
    if req.rating == 0:
        raise HTTPException(400, "rating must be 1 (up) or -1 (down)")
    try:
        return database.add_feedback(req.message_id, req.rating, req.comment or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------------------
# Chat — Server-Sent-Events streaming endpoint
# ---------------------------------------------------------------------------

EMERGENCY_PATTERN = re.compile(
    r"\b(help me|in danger|being attacked|attacked me|kidnap|kidnapped|murder|"
    r"stabbed|shooting|shot at|on fire|fire in|suicide|kill myself|dying|"
    r"accident happened|road accident|bleeding|unconscious)\b",
    re.IGNORECASE,
)


def _format_context(result) -> str:
    if result.is_empty:
        return ""
    lines = []
    for doc, score in zip(result.documents, result.scores):
        lines.append(f"[{doc.source} | relevance {score:.2f}] {doc.answer}")
    return "\n".join(lines)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _follow_up_suggestions(result, exclude_text: str, limit: int = 3) -> list[str]:
    """Cheap, LLM-free 'people also ask' suggestions from the retrieval hits."""
    seen = set()
    suggestions = []
    for doc in result.documents:
        if doc.category != "faq" or doc.text == exclude_text:
            continue
        if doc.text in seen:
            continue
        seen.add(doc.text)
        suggestions.append(doc.text)
        if len(suggestions) >= limit:
            break
    return suggestions


@app.post("/api/chat/stream", tags=["chat"], dependencies=[Depends(enforce_rate_limit)])
def chat_stream(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Message cannot be empty")
    if len(message) > settings.MAX_MESSAGE_LENGTH:
        raise HTTPException(400, f"Message exceeds {settings.MAX_MESSAGE_LENGTH} characters")

    session_id = database.ensure_session(req.session_id)
    history = database.get_messages(session_id)
    is_first_message = len(history) == 0
    database.add_message(session_id, "user", message)
    if is_first_message:
        database.maybe_autotitle(session_id, message)

    def event_stream():
        yield _sse({"type": "session", "session_id": session_id})

        retrieval = rag_engine.search(message)
        sources_payload = [
            {"source": d.source, "text": d.answer, "score": round(s, 3)}
            for d, s in zip(retrieval.documents, retrieval.scores)
        ]
        if sources_payload:
            yield _sse({"type": "sources", "sources": sources_payload})

        is_emergency = bool(EMERGENCY_PATTERN.search(message))
        if is_emergency:
            yield _sse({"type": "emergency"})

        top_doc = retrieval.documents[0] if retrieval.documents else None

        # Fast, fully-offline path: a very confident FAQ match answers
        # directly without needing any LLM provider — keeps the bot useful
        # with zero setup, guarantees a hallucination-free answer, and saves
        # an LLM call whenever the knowledge base already has the answer.
        # It fires for "auto" mode and the explicit "rag_only" (offline)
        # mode; forcing "groq" or "ollama" always calls that model, since
        # picking a provider explicitly is a deliberate choice to bypass it.
        direct_hit = (
            top_doc is not None
            and top_doc.category == "faq"
            and retrieval.top_score >= settings.RAG_DIRECT_ANSWER_SCORE
            and req.provider in ("auto", "rag_only", "")
        )

        full_reply = ""
        provider_used = "rag"
        model_used = "knowledge-base"

        if direct_hit:
            yield _sse({"type": "meta", "provider": "rag", "model": "knowledge-base"})
            for word in top_doc.answer.split(" "):
                full_reply += (word + " ")
                yield _sse({"type": "chunk", "content": word + " "})
            full_reply = full_reply.strip()
        elif req.provider == "rag_only":
            # Offline mode explicitly requested but no confident match found.
            provider_used = "rag"
            model_used = "knowledge-base"
            if top_doc is not None:
                full_reply = (
                    "I don't have a highly confident match, but here's the closest "
                    f"result from my knowledge base:\n\n{top_doc.answer}"
                )
            else:
                full_reply = (
                    "I couldn't find a confident answer in my offline knowledge base "
                    "for that. Try switching to Auto/Groq/Ollama mode, or contact "
                    "your nearest police station."
                )
            yield _sse({"type": "meta", "provider": "rag", "model": "knowledge-base"})
            for word in full_reply.split(" "):
                yield _sse({"type": "chunk", "content": word + " "})
        else:
            context = _format_context(retrieval)
            chat_history = [{"role": m["role"], "content": m["content"]} for m in history]
            had_error = False
            for event in generate_reply(
                user_message=message,
                history=chat_history,
                context=context,
                provider=req.provider,
                model=req.model,
            ):
                if event["type"] == "meta":
                    provider_used = event["provider"]
                    model_used = event["model"]
                    yield _sse(event)
                elif event["type"] == "chunk":
                    full_reply += event["content"]
                    yield _sse(event)
                elif event["type"] == "fallback":
                    had_error = True
                    yield _sse({"type": "warning", "message": event["error"]})

            if had_error and not full_reply.strip():
                # Every LLM provider failed (or none configured) — fall back to
                # the best knowledge-base match so the user still gets a useful
                # reply instead of an error screen.
                provider_used = "rag"
                model_used = "knowledge-base"
                if top_doc is not None:
                    fallback_text = (
                        "I couldn't reach an AI model right now, but here's the closest "
                        f"match from my verified knowledge base:\n\n{top_doc.answer}"
                    )
                else:
                    fallback_text = (
                        "I couldn't reach an AI model right now, and I don't have a "
                        "confident answer from my knowledge base for that. Please try "
                        "again shortly, or contact your nearest police station."
                    )
                full_reply = fallback_text
                yield _sse({"type": "meta", "provider": "rag", "model": "knowledge-base"})
                for word in fallback_text.split(" "):
                    yield _sse({"type": "chunk", "content": word + " "})

        message_id = database.add_message(
            session_id, "assistant", full_reply.strip(),
            provider=provider_used, model=model_used,
            sources=json.dumps(sources_payload) if sources_payload else None,
        )

        suggestions = _follow_up_suggestions(retrieval, exclude_text=message)
        if suggestions:
            yield _sse({"type": "suggestions", "questions": suggestions})

        yield _sse({
            "type": "done",
            "provider": provider_used,
            "model": model_used,
            "message_id": message_id,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ---------------------------------------------------------------------------
# Domain data endpoints (power the quick-action panels in the UI)
# ---------------------------------------------------------------------------

@app.get("/api/emergency", tags=["knowledge-base"])
def emergency_numbers():
    return rag_engine.emergency_snapshot()


@app.get("/api/stations", tags=["knowledge-base"])
def stations(q: str = ""):
    return rag_engine.stations_snapshot(q)


@app.get("/api/legal/search", tags=["knowledge-base"])
def legal_search(q: str):
    if not q.strip():
        raise HTTPException(400, "Query parameter 'q' is required")
    return rag_engine.legal_search(q)


@app.post("/api/complaint/lookup", tags=["complaints"])
def complaint_lookup(req: ComplaintLookupRequest):
    # Check complaints filed through this app first, then the bundled
    # read-only sample dataset used for the lookup demo.
    record = database.find_filed_complaint(req.complaint_id)
    if not record:
        record = find_complaint(req.complaint_id)
    if not record:
        raise HTTPException(404, "No complaint found with that ID")
    return record


@app.post("/api/complaint/file", tags=["complaints"])
def complaint_file(req: ComplaintFileRequest):
    return database.file_complaint(
        crime_type=req.crime_type,
        description=req.description,
        location=req.location,
        complainant_name=req.complainant_name,
        contact=req.contact,
        session_id=req.session_id,
    )


# ---------------------------------------------------------------------------
# Static frontend (served last so it never shadows /api/*)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(BASE_DIR / "frontend"), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
