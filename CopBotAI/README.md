# 🛡️ CopBot AI — Chennai Police Virtual Assistant

A production-grade, full-stack AI chatbot for police & public-safety
assistance — a real retrieval-augmented generation (RAG) pipeline, a
**Groq + Ollama** dual LLM backend, persistent chat history, an analytics
dashboard, and a polished, animated chat UI. Built as a final-year /
portfolio student project, but engineered like a real product: tested,
documented, CI'd, and Docker-ready.

![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![tests](https://img.shields.io/badge/tests-33%20passing-2ea44f)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

---

## ✨ Features

- **Dual LLM pipeline** — plug in a [Groq](https://console.groq.com) API key for
  fast hosted inference, or run fully offline with [Ollama](https://ollama.com)
  (`mistral` by default). Switch providers live from the UI (Auto / Groq /
  Ollama / **Offline knowledge-base-only**) — Auto tries Groq → Ollama →
  the built-in knowledge base, so the bot never just dies mid-conversation.
- **Real domain data, not toy data** — grounded in bundled datasets: 450+
  police FAQs, IPC legal sections with punishments, the 20-station Chennai
  police directory, emergency helpline numbers, and 5000 sample complaint
  records.
- **Retrieval-Augmented Generation** — a TF-IDF semantic search engine
  retrieves the most relevant facts for every question and injects them
  into the model's context, with sources shown per answer. A
  high-confidence FAQ match answers **instantly, with zero LLM calls**.
- **Streaming responses** — token-by-token over Server-Sent Events, with a
  live typing indicator and blinking cursor.
- **Emergency detection** — messages that sound like an active emergency
  automatically surface a banner with 100 / 108 / 101.
- **👍 / 👎 answer feedback** — rate any assistant reply; aggregated on the
  admin dashboard.
- **Follow-up suggestions** — "people also ask"-style chips after every
  answer, generated from the retrieval hits (no extra LLM call).
- **File & Track a Complaint** — an interactive demo flow: file a new
  complaint and get a trackable ID, or look up an existing one.
- **📊 Analytics dashboard** (`/admin.html`) — Chart.js visualizations of
  message volume, provider usage split, complaints by type, and feedback —
  powered by `GET /api/stats`.
- **Rate limiting** — an in-memory sliding-window limiter protects
  `/api/chat/stream` from abuse, tuned via `.env`.
- **Persistent chat history** — conversations are saved server-side
  (SQLite) and browsable from the sidebar, resumable after a restart.
- **Polished, animated UI** — dark/light themes, smooth animations,
  mobile-responsive, voice input (Web Speech API), one-click copy.
- **Tested & CI'd** — 33 automated tests (`pytest` + FastAPI `TestClient`)
  covering data loading, retrieval quality, and every API endpoint,
  including the SSE stream itself; GitHub Actions runs them on Python
  3.10/3.11/3.12 on every push.
- **Zero front-end build step** — plain HTML/CSS/JS, loads instantly.

📖 See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the full tech-stack
breakdown, request-lifecycle diagram, module map, and "how to extend this"
notes.

---

## 🚀 Quick start (extract & run)

**Requirements:** Python 3.10+

```bash
cd CopBotAI

# One command: creates a venv, installs deps, and starts the server
./run.sh          # macOS/Linux
run.bat           # Windows
```

Open **http://localhost:8000** — done. CopBot works immediately with
**zero API keys**, answering from its built-in knowledge base
(`provider: rag_only` / "Offline" mode).

Visit **http://localhost:8000/admin.html** for the live analytics
dashboard, and **http://localhost:8000/docs** for interactive Swagger API
docs.

### Enable full AI answers (recommended)

Copy `.env.example` to `.env` and set **at least one** of:

```ini
# Fast, hosted — get a free key at https://console.groq.com/keys
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# OR fully local/private — install Ollama, then:
#   ollama pull mistral
#   ollama serve
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
```

Restart the app — the green status dots in the sidebar confirm each
provider is reachable.

### Manual setup (any OS) / using `make`

```bash
make dev          # venv + runtime + dev/test deps
cp .env.example .env
make test          # run the 33-test suite
make run            # start the server
```

or without Make:

```bash
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env             # then edit with your keys
python -m backend.main
```

### Docker

```bash
docker compose up --build
```

This also spins up a local Ollama container. Remove the `ollama` service
from `docker-compose.yml` if you only intend to use Groq.

---

## 🧪 Running the tests

```bash
make test
# or:
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

33 tests across `tests/test_data_loader.py`, `tests/test_rag_engine.py`,
and `tests/test_api.py` — including a full SSE-stream integration test,
rate-limit behavior, and the complete file→lookup complaint flow. Each
test runs against an isolated temp SQLite database (see
`tests/conftest.py`), so `pytest` never touches your real `data/*.db`.

CI (`.github/workflows/ci.yml`) runs the same suite on every push/PR
across Python 3.10, 3.11, and 3.12.

---

## 🏗️ Project structure

```
CopBotAI/
├── backend/
│   ├── main.py            # FastAPI app: REST + SSE streaming chat endpoint
│   ├── llm_service.py      # Groq + Ollama unified client, streaming & fallback
│   ├── rag_engine.py        # TF-IDF retrieval over the bundled datasets
│   ├── data_loader.py       # Loads/normalizes the JSON datasets
│   ├── database.py          # SQLite: sessions, messages, feedback, complaints, stats
│   ├── rate_limit.py         # In-memory sliding-window rate limiter
│   ├── models.py            # Pydantic request/response schemas
│   └── config.py            # Central, env-driven configuration
├── data/                    # FAQ, IPC legal database, stations, emergency, complaints
├── frontend/
│   ├── index.html            # Chat UI
│   ├── admin.html             # Analytics dashboard (Chart.js)
│   ├── css/style.css          # Design system, animations, dark/light themes
│   └── js/app.js              # SSE streaming client, sessions, modals, feedback
├── tests/                    # pytest suite (33 tests)
├── .github/workflows/ci.yml   # GitHub Actions CI
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt         # + pytest/httpx for testing
├── Makefile                     # make dev / test / run / docker-up
├── .env.example
├── run.sh / run.bat
├── Dockerfile / docker-compose.yml
├── ARCHITECTURE.md               # Tech stack + design notes (read this!)
├── CONTRIBUTING.md
└── LICENSE (MIT)
```

---

## 🔌 API reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Provider connectivity + knowledge base stats |
| `/api/config` | GET | Public runtime config for the frontend |
| `/api/stats` | GET | Aggregate usage stats (admin dashboard) |
| `/api/chat/stream` | POST | SSE streaming chat (`{message, session_id, provider}`) |
| `/api/feedback` | POST | Rate a message (`{message_id, rating: 1\|-1}`) |
| `/api/sessions` | GET / POST | List / create chat sessions |
| `/api/sessions/{id}/messages` | GET | Full message history for a session |
| `/api/sessions/{id}` | DELETE | Delete a session |
| `/api/emergency` | GET | Emergency helpline directory |
| `/api/stations?q=` | GET | Search Chennai police stations |
| `/api/legal/search?q=` | GET | Search IPC sections |
| `/api/complaint/lookup` | POST | Look up a complaint by ID (filed or sample data) |
| `/api/complaint/file` | POST | File a new complaint, get back a trackable ID |

Interactive Swagger docs: **`/docs`**. Full request/response flow and
design rationale: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## ☁️ Deploying

**Any platform that runs a Python web service works.** The app reads its
port from `$PORT` (falls back to `8000`), so most PaaS providers work with
zero config changes.

### Render / Railway / Fly.io (typical PaaS flow)

1. Push this repo to GitHub (see [below](#-pushing-to-github)).
2. Create a new **Web Service** from your repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python -m backend.main` (or `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`)
5. Add environment variables from `.env.example` (at minimum `GROQ_API_KEY`
   if you want hosted AI answers — the app works without it too).
6. Deploy. SQLite lives on local disk, so use your platform's persistent
   disk/volume feature if you want chat history to survive redeploys —
   otherwise it simply starts fresh each deploy, which is fine for a demo.

### Docker (any VPS / cloud run / ECS / etc.)

```bash
docker build -t copbot-ai .
docker run -p 8000:8000 --env-file .env copbot-ai
```

or the full stack with a local Ollama sidecar:

```bash
docker compose up --build -d
```

### Notes for a real production deployment

- Swap the in-memory rate limiter (`backend/rate_limit.py`) for a
  Redis-backed one if you run multiple worker processes/instances.
- Swap SQLite for Postgres if you need concurrent writers at scale (see
  "Change the database" in `ARCHITECTURE.md`).
- Put a real reverse proxy (nginx/Caddy) or your PaaS's HTTPS termination
  in front of Uvicorn.

---

## 📦 Pushing to GitHub

This repo is already `git`-ready (`.gitignore` excludes `.venv/`, `.env`,
`*.db`, caches, etc.).

```bash
cd CopBotAI
git init
git add .
git commit -m "Initial commit: CopBot AI"
git branch -M main
git remote add origin https://github.com/<your-username>/copbot-ai.git
git push -u origin main
```

GitHub Actions CI will pick up automatically from `.github/workflows/ci.yml`
on your next push.

---

## 🧩 Swapping in your own data / model

- Drop new rows into `data/faq.json` or `data/legal_database.json` (same
  shape as the existing entries) and restart — the RAG index rebuilds
  automatically at startup.
- Change `GROQ_MODEL` / `OLLAMA_MODEL` in `.env` to any model your account
  or local Ollama install supports.
- Adding a brand-new LLM provider (OpenAI, Anthropic, etc.) is a one-file
  change — see "Extending the project" in `ARCHITECTURE.md`.
- All tunables (retrieval thresholds, history length, rate limits,
  timeouts) live in `backend/config.py` / `.env.example`.

---

## ⚠️ Disclaimer

CopBot AI is an informational assistant, not a substitute for official
police action or legal advice. For real emergencies, always call your
local emergency number immediately.
