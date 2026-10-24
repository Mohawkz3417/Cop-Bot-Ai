from backend.data_loader import (
    find_complaint,
    load_emergency_services,
    load_faq,
    load_legal_sections,
    load_police_stations,
)


def test_faq_loads_and_is_well_formed():
    faq = load_faq()
    assert len(faq) > 100
    for item in faq[:5]:
        assert item["question"]
        assert item["answer"]


def test_legal_sections_deduplicated():
    sections = load_legal_sections()
    assert len(sections) > 0
    keys = [(s["section"], s["offense"]) for s in sections]
    assert len(keys) == len(set(keys)), "legal sections should be deduplicated"


def test_police_stations_loaded():
    stations = load_police_stations()
    assert len(stations) == 20
    assert all(s["name"] for s in stations)


def test_emergency_services_loaded():
    services = load_emergency_services()
    assert len(services) == 20
    numbers = {s["number"] for s in services}
    assert "100" in numbers  # police emergency


def test_find_complaint_known_id():
    # 410932 is a known sample id bundled in data/complaint_records.json
    record = find_complaint("410932")
    assert record is not None
    assert record["complaint_id"] == "410932"


def test_find_complaint_unknown_id():
    assert find_complaint("no-such-id-000000") is None
