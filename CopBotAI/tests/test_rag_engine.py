from backend.rag_engine import rag_engine


def setup_module(_module):
    rag_engine.build()


def test_index_builds_with_documents():
    assert len(rag_engine.documents) > 100


def test_emergency_query_matches_emergency_category():
    result = rag_engine.search("What are the emergency helpline numbers in Chennai?")
    assert not result.is_empty
    assert result.documents[0].category == "emergency"


def test_legal_query_matches_correct_ipc_section():
    result = rag_engine.search("What is the punishment under IPC 302?")
    assert not result.is_empty
    assert result.documents[0].category == "legal"
    assert "302" in result.documents[0].text


def test_station_query_matches_station_category():
    result = rag_engine.search("Find the nearest police station in Chennai")
    assert not result.is_empty
    assert result.documents[0].category == "station"


def test_irrelevant_query_returns_low_or_no_confidence():
    result = rag_engine.search("asdkjaslkdjalksjd nonsense gibberish query 12345")
    # Either nothing clears the minimum score threshold, or if something
    # does, it should not be a suspiciously high-confidence match.
    assert result.is_empty or result.top_score < 0.5


def test_legal_search_helper():
    hits = rag_engine.legal_search("murder punishment")
    assert hits
    assert any("302" in h["section"] for h in hits)
