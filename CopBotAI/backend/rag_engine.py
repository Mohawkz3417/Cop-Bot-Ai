"""
Lightweight retrieval-augmented-generation engine.

Design goals:
- No heavyweight/downloaded ML models required to boot (works fully offline,
  starts in well under a second, and needs no GPU).
- Deterministic, explainable retrieval over the bundled police FAQ + IPC
  legal database + Chennai station/emergency directories using TF-IDF
  cosine similarity (scikit-learn).
- Used two ways:
    1. As a fast, reliable answer path when a query closely matches a known
       FAQ (works even with zero LLM providers configured).
    2. As grounding context ("citations") injected into the LLM prompt so
       Groq/Ollama answers stay accurate and on-domain instead of
       hallucinating legal advice.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.config import settings
from backend.data_loader import (
    load_emergency_services,
    load_faq,
    load_legal_sections,
    load_police_stations,
)

logger = logging.getLogger("copbot.rag")


@dataclass
class Document:
    id: str
    text: str          # text that gets embedded / matched against
    answer: str         # text shown to the user / fed to the LLM as context
    source: str          # human readable source label
    category: str


@dataclass
class RetrievalResult:
    documents: list[Document] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)

    @property
    def top_score(self) -> float:
        return self.scores[0] if self.scores else 0.0

    @property
    def is_empty(self) -> bool:
        return not self.documents


def _clean(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class RAGEngine:
    """Thread-safe, lazily-built TF-IDF index over all bundled datasets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._built = False
        self.documents: list[Document] = []
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None

    def build(self) -> None:
        with self._lock:
            if self._built:
                return
            docs: list[Document] = []

            for i, item in enumerate(load_faq()):
                docs.append(Document(
                    id=f"faq-{i}",
                    text=item["question"],
                    answer=item["answer"],
                    source="Police FAQ",
                    category="faq",
                ))

            for i, item in enumerate(load_legal_sections()):
                text = f"{item['section']} {item['offense']}"
                answer = (
                    f"**{item['section']}** — {item['offense']}. "
                    f"Prescribed punishment: {item['punishment']}."
                )
                docs.append(Document(
                    id=f"legal-{i}",
                    text=text,
                    answer=answer,
                    source="IPC Legal Database",
                    category="legal",
                ))

            for i, item in enumerate(load_police_stations()):
                text = f"{item['name']} {item['district']} police station contact"
                answer = (
                    f"**{item['name']}** ({item['district']}) — "
                    f"Phone: {item['contact']}, Email: {item['email']}."
                )
                docs.append(Document(
                    id=f"station-{i}",
                    text=text,
                    answer=answer,
                    source="Chennai Police Stations Directory",
                    category="station",
                ))

            for i, item in enumerate(load_emergency_services()):
                text = f"{item['service']} emergency number helpline"
                answer = (
                    f"**{item['service']}**: dial **{item['number']}** "
                    f"({item['availability']}, {item['department']})."
                )
                docs.append(Document(
                    id=f"emergency-{i}",
                    text=text,
                    answer=answer,
                    source="Emergency Services Directory",
                    category="emergency",
                ))

            if not docs:
                logger.warning("RAG engine built with zero documents — check data/ files.")
                self._built = True
                return

            corpus = [_clean(d.text) for d in docs]
            vectorizer = TfidfVectorizer(
                ngram_range=(1, 2),
                min_df=1,
                max_df=0.9,
                sublinear_tf=True,
                stop_words="english",
            )
            matrix = vectorizer.fit_transform(corpus)

            self.documents = docs
            self.vectorizer = vectorizer
            self.matrix = matrix
            self._built = True
            logger.info("RAG index built with %d documents", len(docs))

    def search(self, query: str, top_k: int | None = None) -> RetrievalResult:
        if not self._built:
            self.build()
        if not self.documents or self.vectorizer is None:
            return RetrievalResult()

        top_k = top_k or settings.RAG_TOP_K
        q_vec = self.vectorizer.transform([_clean(query)])
        sims = cosine_similarity(q_vec, self.matrix)[0]

        ranked = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)
        docs, scores = [], []
        for idx in ranked[:top_k]:
            score = float(sims[idx])
            if score < settings.RAG_MIN_SCORE:
                continue
            docs.append(self.documents[idx])
            scores.append(score)

        return RetrievalResult(documents=docs, scores=scores)

    def emergency_snapshot(self) -> list[dict]:
        return load_emergency_services()

    def stations_snapshot(self, query: str = "") -> list[dict]:
        stations = load_police_stations()
        if not query:
            return stations
        q = query.lower()
        return [s for s in stations if q in s["name"].lower() or q in s["district"].lower()]

    def legal_search(self, query: str, top_k: int = 5) -> list[dict]:
        result = self.search(query, top_k=top_k * 3)
        legal_docs = [d for d in result.documents if d.category == "legal"][:top_k]
        return [{"section": d.text, "detail": d.answer} for d in legal_docs]


rag_engine = RAGEngine()
