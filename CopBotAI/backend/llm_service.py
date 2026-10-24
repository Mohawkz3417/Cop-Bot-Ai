"""
Unified LLM pipeline for CopBot AI.

Supports two interchangeable providers behind one interface:
  - Groq   : fast, hosted inference over an OpenAI-compatible REST API.
  - Ollama : local inference (recommended model: mistral) via the Ollama
             REST API, for fully private / offline deployments.

Both are implemented with plain `requests` calls (no vendor SDK required),
which keeps setup to "drop an API key in .env" for Groq and
"ollama pull mistral && ollama serve" for Ollama.

`generate_reply()` is the single entry point the API layer calls. It:
  1. Picks a provider (explicit choice, or "auto" -> Groq -> Ollama -> local).
  2. Streams tokens back as they arrive (generator of str chunks).
  3. Transparently falls back to the next provider (or to a RAG-only
     canned answer) if the chosen provider errors out, so the chatbot
     never just dies mid-conversation.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Generator

import requests

from backend.config import settings

logger = logging.getLogger("copbot.llm")

SYSTEM_PROMPT = """You are CopBot AI, a friendly, precise virtual assistant for the \
Chennai City Police, built to help the public with police procedures, filing \
complaints (FIR), Indian Penal Code (IPC) legal sections, emergency contacts, \
and general public-safety questions.

Rules you must always follow:
- Be concise, warm, and easy to understand. Use short paragraphs or bullet points.
- When the provided CONTEXT contains relevant facts (FAQ answers, IPC sections, \
station contacts, emergency numbers), ground your answer in them and prefer \
their exact numbers/contacts over guessing.
- If a situation sounds like an active emergency (violence in progress, someone \
in danger right now, fire, medical emergency), your first line must tell the \
person to immediately call 100 (Police), 108 (Ambulance) or 101 (Fire) as \
appropriate, before anything else.
- You are not a lawyer and cannot give binding legal advice or guarantee case \
outcomes; say so briefly when relevant and suggest consulting a lawyer or the \
nearest police station for official action.
- Never invent a law, section number, phone number, or procedure. If you are \
not sure and no context is provided, say so honestly and suggest the person \
contact their local police station.
- Keep answers focused and skimmable; avoid long generic disclaimers.
"""


class ProviderError(Exception):
    def __init__(self, provider: str, message: str):
        super().__init__(message)
        self.provider = provider
        self.message = message


def _build_messages(user_message: str, history: list[dict], context: str) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({
            "role": "system",
            "content": f"CONTEXT (retrieved from CopBot's verified knowledge base):\n{context}",
        })
    for turn in history[-settings.MAX_HISTORY_TURNS:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": user_message})
    return messages


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------

def _stream_groq(messages: list[dict], model: str) -> Generator[str, None, None]:
    if not settings.GROQ_API_KEY:
        raise ProviderError("groq", "GROQ_API_KEY is not configured")

    url = f"{settings.GROQ_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or settings.GROQ_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": 0.4,
        "max_tokens": 1024,
    }

    try:
        with requests.post(url, headers=headers, json=payload,
                            stream=True, timeout=settings.REQUEST_TIMEOUT) as resp:
            if resp.status_code != 200:
                raise ProviderError("groq", f"Groq API returned {resp.status_code}: {resp.text[:300]}")
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                data = raw_line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
    except requests.RequestException as e:
        raise ProviderError("groq", f"Could not reach Groq: {e}") from e


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def _stream_ollama(messages: list[dict], model: str) -> Generator[str, None, None]:
    url = f"{settings.OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model or settings.OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.4},
    }
    try:
        with requests.post(url, json=payload, stream=True,
                            timeout=settings.REQUEST_TIMEOUT) as resp:
            if resp.status_code != 200:
                raise ProviderError("ollama", f"Ollama returned {resp.status_code}: {resp.text[:300]}")
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if chunk.get("done"):
                    break
                content = chunk.get("message", {}).get("content")
                if content:
                    yield content
    except requests.RequestException as e:
        raise ProviderError(
            "ollama",
            f"Could not reach Ollama at {settings.OLLAMA_BASE_URL}. "
            f"Is it running? ({e})",
        ) from e


# ---------------------------------------------------------------------------
# Health checks (used by /api/health and the UI status dots)
# ---------------------------------------------------------------------------

def check_groq() -> dict:
    if not settings.GROQ_API_KEY:
        return {"provider": "groq", "available": False, "detail": "No API key configured"}
    try:
        resp = requests.get(
            f"{settings.GROQ_BASE_URL}/models",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            timeout=5,
        )
        return {"provider": "groq", "available": resp.status_code == 200,
                "detail": "Connected" if resp.status_code == 200 else f"HTTP {resp.status_code}"}
    except requests.RequestException as e:
        return {"provider": "groq", "available": False, "detail": str(e)}


def check_ollama() -> dict:
    try:
        resp = requests.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code == 200:
            models = [m.get("name") for m in resp.json().get("models", [])]
            return {"provider": "ollama", "available": True, "detail": "Connected", "models": models}
        return {"provider": "ollama", "available": False, "detail": f"HTTP {resp.status_code}"}
    except requests.RequestException as e:
        return {"provider": "ollama", "available": False, "detail": "Not running / unreachable"}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_reply(
    user_message: str,
    history: list[dict],
    context: str,
    provider: str = "auto",
    model: str = "",
) -> Generator[dict, None, None]:
    """
    Yields dicts of the shape {"type": "chunk"|"meta"|"error", ...} so the
    API layer can turn this straight into a Server-Sent Events stream.
    """
    messages = _build_messages(user_message, history, context)
    provider = (provider or settings.DEFAULT_PROVIDER).lower()

    order: list[str]
    if provider == "groq":
        order = ["groq"]
    elif provider == "ollama":
        order = ["ollama"]
    else:
        order = ["groq", "ollama"]

    last_error = None
    for candidate in order:
        try:
            stream_fn = _stream_groq if candidate == "groq" else _stream_ollama
            used_model = model or (settings.GROQ_MODEL if candidate == "groq" else settings.OLLAMA_MODEL)
            yield {"type": "meta", "provider": candidate, "model": used_model}
            produced = False
            for piece in stream_fn(messages, model):
                produced = True
                yield {"type": "chunk", "content": piece}
            if produced:
                return
            last_error = f"{candidate} returned an empty response"
        except ProviderError as e:
            logger.warning("Provider %s failed: %s", e.provider, e.message)
            last_error = e.message
            continue

    yield {"type": "fallback", "error": last_error or "No LLM provider is configured or reachable."}
