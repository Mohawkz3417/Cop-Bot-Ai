"""
Central configuration for CopBot AI.
All values can be overridden with environment variables (see .env.example).
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "data" / "copbot_history.db"


def _bool(val: str, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # --- App ---
    APP_NAME = "CopBot AI"
    APP_VERSION = "2.0.0"
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    DEBUG = _bool(os.getenv("DEBUG"), False)
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

    # --- LLM provider selection ---
    # "auto"  -> try Groq first, fall back to Ollama, fall back to local RAG-only answers
    # "groq"  -> force Groq
    # "ollama"-> force Ollama
    DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "auto")

    # --- Groq (cloud, fast inference) ---
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # --- Ollama (local, private inference) ---
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")

    # --- RAG ---
    RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
    RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.12"))
    RAG_DIRECT_ANSWER_SCORE = float(os.getenv("RAG_DIRECT_ANSWER_SCORE", "0.62"))

    # --- Safety / limits ---
    MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))
    MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "12"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))

    # --- Rate limiting (in-memory sliding window per client IP) ---
    RATE_LIMIT_ENABLED = _bool(os.getenv("RATE_LIMIT_ENABLED"), True)
    RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "20"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


settings = Settings()
