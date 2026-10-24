"""
Loads and normalizes the bundled police-domain datasets into simple,
predictable Python structures used by the RAG engine and the REST API.
"""
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.config import DATA_DIR

logger = logging.getLogger("copbot.data")


def _read_json(path: Path) -> Any:
    if not path.exists():
        logger.warning("Data file missing: %s", path)
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _sheet_rows(raw: Any) -> list:
    """The source datasets were exported from Excel and wrapped as {"Sheet1": [...]}"""
    if raw is None:
        return []
    if isinstance(raw, dict) and "Sheet1" in raw:
        return raw["Sheet1"]
    if isinstance(raw, list):
        return raw
    return []


@lru_cache(maxsize=1)
def load_faq() -> list[dict]:
    raw = _read_json(DATA_DIR / "faq.json") or []
    out = []
    for item in raw:
        q = (item.get("Question") or "").strip()
        a = (item.get("Answer") or "").strip()
        if q and a:
            out.append({"question": q, "answer": a})
    logger.info("Loaded %d FAQ entries", len(out))
    return out


@lru_cache(maxsize=1)
def load_legal_sections() -> list[dict]:
    rows = _sheet_rows(_read_json(DATA_DIR / "legal_database.json"))
    out = []
    seen = set()
    for r in rows:
        section = (r.get("Section") or "").strip()
        offense = (r.get("Offense") or "").strip()
        punishment = (r.get("Punishment") or "").strip()
        key = (section, offense)
        if not section or key in seen:
            continue
        seen.add(key)
        out.append({"section": section, "offense": offense, "punishment": punishment})
    logger.info("Loaded %d legal sections", len(out))
    return out


@lru_cache(maxsize=1)
def load_police_stations() -> list[dict]:
    rows = _sheet_rows(_read_json(DATA_DIR / "police_stations.json"))
    out = []
    for r in rows:
        out.append({
            "district": r.get("District", ""),
            "name": r.get("Police Station Name", ""),
            "contact": r.get("Contact Number", ""),
            "email": r.get("Email", ""),
            "location": r.get("Location (Lat, Long)", ""),
        })
    logger.info("Loaded %d police stations", len(out))
    return out


@lru_cache(maxsize=1)
def load_emergency_services() -> list[dict]:
    rows = _sheet_rows(_read_json(DATA_DIR / "emergency_services.json"))
    out = []
    for r in rows:
        out.append({
            "service": r.get("Service", ""),
            "number": r.get("Emergency Number", ""),
            "availability": r.get("Availability", ""),
            "department": r.get("Department", ""),
        })
    logger.info("Loaded %d emergency services", len(out))
    return out


@lru_cache(maxsize=1)
def load_complaints_index() -> dict[str, dict]:
    rows = _sheet_rows(_read_json(DATA_DIR / "complaint_records.json"))
    index = {}
    for r in rows:
        cid = str(r.get("Complaint_ID", "")).strip()
        if cid:
            index[cid] = {
                "complaint_id": cid,
                "crime_type": r.get("Crime_Type", ""),
                "date_reported": r.get("Date_Reported", ""),
                "status": r.get("Status", ""),
                "police_station_id": r.get("Police_Station_ID", ""),
            }
    logger.info("Loaded %d complaint records", len(index))
    return index


def find_complaint(complaint_id: str) -> dict | None:
    return load_complaints_index().get(str(complaint_id).strip())
