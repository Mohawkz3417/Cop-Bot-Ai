# CopBot AI — Architecture & Tech Stack Notes

This document explains **what each part of the system does, why it was
built that way, and how the pieces connect** — useful both for your own
understanding/viva and for anyone extending the project.

---

## 1. Tech stack at a glance

| Layer | Technology | Why |
|---|---|---|
| Backend framework | **FastAPI** (Python 3.10+) | Async-first, automatic OpenAPI docs at `/docs`, native `StreamingResponse` for SSE, Pydantic validation out of the box. |
| Server | **Uvicorn** | ASGI server that runs FastAPI; ships with `[standard]` extras for production performance. |
| LLM providers | **Groq** (hosted) + **Ollama** (local) | Two interchangeable inference backends reached over plain HTTP — no vendor SDK lock-in. Groq gives fast, free-tier-friendly cloud inference; Ollama gives fully private/offline inference. |
| Retrieval (RAG) | **scikit-learn TF-IDF + cosine similarity** | Deterministic, explainable, instant-start semantic search — no model download, no GPU, no network call. Chosen over sentence-transformer embeddings specifically so the app boots and answers in well under a second with zero setup. |
| Persistence | **SQLite** (stdlib `sqlite3`) | Zero-config embedded database; the `.db` file is created automatically. Stores chat sessions/messages, per-message feedback, and complaints filed through the app. |
| Frontend | **Vanilla HTML/CSS/JS** (no framework, no build step) | Loads instantly, has zero `npm install`, and is easy for a student project to read end-to-end. Uses `marked.js` + `DOMPurify` (CDN) for safe markdown rendering and `Chart.js` (CDN) for the analytics dashboard. |
| Streaming transport | **Server-Sent Events (SSE)** | Simpler than WebSockets for one-directional token streaming; works over plain HTTP/1.1, easy to consume with `fetch()` + `ReadableStream`. |
| Testing | **pytest + FastAPI TestClient** | 30+ tests covering data loading, retrieval quality, and every API endpoint (including the SSE stream itself). |
| CI | **GitHub Actions** | Runs the full test suite on Python 3.10/3.11/3.12 on every push/PR. |
| Deployment | **Docker + docker-compose** (optional) | One command to run the API and an Ollama sidecar container together. |

---

## 2. Request lifecycle: a chat message end to end

```
Browser                     FastAPI (backend/main.py)              Data / Models
   │                                │                                     │
   │  POST /api/chat/stream         │                                     │
   ├───────────────────────────────►│                                     │
   │                                │ 1. rate_limit.enforce_rate_limit()  │
   │                                │ 2. database.ensure_session()        │
   │                                │ 3. rag_engine.search(message) ──────┼──► TF-IDF cosine similarity
   │                                │    over faq/legal/station/emergency │    over 490+ indexed documents
   │                                │    documents                        │
   │ ◄── SSE: sources ──────────────┤ 4. yield matched sources            │
   │ ◄── SSE: emergency (if any) ───┤ 5. regex emergency-phrase check     │
   │                                │ 6. Decide path:                     │
   │                                │    a) high-confidence FAQ match     │
   │                                │       → answer directly (no LLM)    │
   │                                │    b) else → llm_service.generate_  │
   │                                │       reply() with RAG context ─────┼──► Groq API / Ollama API
   │ ◄── SSE: meta, chunk×N ────────┤    c) all providers failed          │    (streamed token-by-token)
   │                                │       → fall back to best RAG hit   │
   │                                │ 7. database.add_message() ──────────┼──► SQLite
   │ ◄── SSE: suggestions ──────────┤ 8. follow-up FAQ suggestions        │
   │ ◄── SSE: done (message_id) ────┤                                     │
```

The whole exchange is one HTTP request whose body is a stream of
`data: {...}\n\n` JSON events — see `frontend/js/app.js`'s `sendMessage()`
for the client-side parser, and `backend/main.py`'s `chat_stream()` /
`event_stream()` for the server-side generator.

---

## 3. Module map (`backend/`)

- **`config.py`** — every tunable in one place, all overridable via `.env`. Nothing else in the codebase reads `os.environ` directly.
- **`data_loader.py`** — reads the bundled JSON datasets (`data/*.json`) once and normalizes their shape (`@lru_cache`d, so parsing only happens on first use).
- **`rag_engine.py`** — builds one TF-IDF index across all four datasets (FAQ, IPC legal sections, police stations, emergency numbers) and exposes `.search()`, `.legal_search()`, `.stations_snapshot()`, `.emergency_snapshot()`.
- **`llm_service.py`** — the Groq/Ollama pipeline. `generate_reply()` is the single entry point: it tries providers in order (explicit choice, or Groq → Ollama for "auto"), streams tokens, and reports which provider actually answered.
- **`database.py`** — all SQLite access (sessions, messages, feedback, filed complaints, aggregate stats). Every other module goes through this file rather than touching `sqlite3` directly.
- **`rate_limit.py`** — an in-memory sliding-window limiter guarding `/api/chat/stream` from abuse.
- **`models.py`** — Pydantic request schemas (validation + OpenAPI docs for free).
- **`main.py`** — wires everything into FastAPI routes and mounts the static frontend.

---

## 4. Why a fast-path "direct answer" mode?

When a user's question is a near-exact match for a bundled FAQ
(`retrieval.top_score >= RAG_DIRECT_ANSWER_SCORE`, default `0.62`), CopBot
answers **directly from the knowledge base with zero LLM calls**. This is
deliberate:

1. **Reliability** — the app is fully useful even with no Groq/Ollama configured at all (see `provider: "rag_only"`, the "Offline (Knowledge Base)" option in the UI).
2. **Speed & cost** — skips a network round-trip to an LLM for questions we already have a verified answer to.
3. **Zero hallucination** — a canned, human-reviewed FAQ answer can't invent a wrong law or phone number.

Forcing a specific provider (`groq` or `ollama` in the dropdown) always
calls that model instead — picking a provider is a deliberate choice to
bypass the fast path.

---

## 5. Feature list (v3)

| Feature | Where |
|---|---|
| Streaming chat with typing indicator | `frontend/js/app.js`, `POST /api/chat/stream` |
| Dual LLM pipeline (Groq + Ollama) with auto-fallback | `backend/llm_service.py` |
| Offline knowledge-base-only mode | `provider: "rag_only"` |
| RAG grounding + visible sources per answer | `rag_engine.py`, `sources` SSE event |
| Emergency phrase detection banner | `EMERGENCY_PATTERN` regex in `main.py` |
| Persistent, resumable chat history | `database.py` sessions/messages tables |
| 👍 / 👎 message feedback | `POST /api/feedback`, `feedback` table |
| Follow-up ("people also ask") suggestion chips | `_follow_up_suggestions()`, `suggestions` SSE event |
| File a Complaint (interactive demo) | `POST /api/complaint/file`, `filed_complaints` table |
| Track a Complaint (by ID, filed or sample data) | `POST /api/complaint/lookup` |
| IPC legal section search | `GET /api/legal/search` |
| Police station directory search | `GET /api/stations` |
| Emergency helpline directory | `GET /api/emergency` |
| Analytics dashboard (Chart.js) | `frontend/admin.html`, `GET /api/stats` |
| Rate limiting | `backend/rate_limit.py` |
| Dark/light themes, voice input, mobile-responsive UI | `frontend/css/style.css`, `frontend/js/app.js` |
| Automated tests (33) | `tests/` |
| CI on every push | `.github/workflows/ci.yml` |
| Docker / docker-compose | `Dockerfile`, `docker-compose.yml` |

---

## 6. Extending the project (common changes)

**Add a new LLM provider** (e.g. OpenAI): add a `_stream_openai()` function
in `llm_service.py` following the same generator shape as `_stream_groq()`
(yield plain string chunks), add it to the `order` list in
`generate_reply()`, and add its config to `config.py` / `.env.example`.
Nothing else needs to change — `main.py` and the frontend already treat
"provider" as an opaque string.

**Add more knowledge-base data**: drop rows into any `data/*.json` file in
the same shape as the existing entries (see `data_loader.py` for the exact
fields expected), restart the server — the RAG index rebuilds
automatically on startup. No re-training, no embeddings pipeline.

**Change the database**: everything SQL lives in `database.py`. Swapping
SQLite for Postgres means replacing the `sqlite3.connect(...)` in
`_get_conn()` with a real connection pool (e.g. `psycopg2`/`asyncpg`) and
adjusting the few SQLite-specific bits (`DATE()`, `AUTOINCREMENT`).
Everything above that function is unaffected.

**Add a new API endpoint**: add a Pydantic model to `models.py` if it
needs a request body, add the route to `main.py`, and (if it touches the
knowledge base) add a helper method to `rag_engine.py`. Add a test in
`tests/test_api.py` following the existing pattern.
