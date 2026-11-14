"""Comprehensive test suite verifying 100% adherence to Frontend API contract.

Matches Frontend/src/lib/types.ts, api.ts, ContractChecks.tsx, and API_ASSUMPTIONS.md.
"""

from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.services.ai_proxy import ai_proxy_service


@pytest.fixture(scope="module")
def client():
    """Create test client with lifespan context active."""
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Health & Root Endpoints
# ---------------------------------------------------------------------------
def test_health_contract(client):
    """GET /health must match Dinith's HealthResponse schema."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "v0.1-hackathon"
    assert isinstance(data["sqlite_connected"], bool)
    assert isinstance(data["ai_service_configured"], bool)
    assert data["disclaimer"] == "v0.1, unverified"


def test_root_endpoint(client):
    """GET / returns system info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["disclaimer"] == "v0.1, unverified"


# ---------------------------------------------------------------------------
# Ask Endpoint (POST /ask & POST /cache/clear)
# ---------------------------------------------------------------------------
def test_ask_answerable_moon_query(client):
    """POST /ask for answerable moon base question returns grounded=True with 2-4 citations."""
    payload = {"question": "Which tested materials are risky at the Moon Base's 30% oxygen?"}
    response = client.post("/ask", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["grounded"] is True
    assert len(data["answer"]) > 50
    # Must have 2 to 4 citations
    assert 2 <= len(data["citations"]) <= 4
    for cit in data["citations"]:
        assert len(cit["paper_title"]) > 0
        assert len(cit["investigation"]) > 0
        assert len(cit["quote"]) > 0

    assert data["evidence"] is not None
    assert data["evidence"]["test_count"] >= 0
    assert data["evidence"]["platform"] in ["iss", "drop_tower", "other"]
    assert data["evidence"]["strength"] in ["low", "medium", "high"]
    assert isinstance(data["latency_ms"], (int, float))


def test_ask_unanswerable_query(client):
    """POST /ask for unanswerable question MUST return grounded=False, answer='', citations=[], evidence=None."""
    payload = {"question": "What is the boiling point of lunar regolith tea?"}
    response = client.post("/ask", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["grounded"] is False
    assert data["answer"] == ""  # Hard requirement: must be empty string
    assert data["citations"] == []  # Hard requirement: must be empty array
    assert data["evidence"] is None  # Hard requirement: must be null
    assert isinstance(data["latency_ms"], (int, float))


def test_ask_cache_and_clear(client):
    """Verify cache works on repeated queries and can be cleared via POST /cache/clear."""
    ai_proxy_service.clear_cache()

    q = "  which tested materials are risky at the moon base's 30% OXYGEN?  "
    resp1 = client.post("/ask", json={"question": q})
    assert resp1.status_code == 200

    # Repeat call: should hit in-memory cache
    resp2 = client.post("/ask", json={"question": q})
    assert resp2.status_code == 200
    assert resp2.json()["grounded"] is True

    # Clear cache
    clear_resp = client.post("/cache/clear")
    assert clear_resp.status_code == 200
    clear_data = clear_resp.json()
    assert clear_data["cleared"] is True
    assert clear_data["entries_cleared"] >= 1


# ---------------------------------------------------------------------------
# Investigations Endpoint (GET /investigations)
# ---------------------------------------------------------------------------
def test_get_investigations_raw_array(client):
    """GET /investigations returns a raw JSON array Investigation[] (NOT a wrapped object)."""
    response = client.get("/investigations")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0

    for inv in data:
        assert "id" in inv
        assert "name" in inv
        assert "hardware" in inv
        assert inv["pillar"] in ["prevention", "detection", "suppression", "supporting"]
        assert "fuels" in inv
        assert isinstance(inv["fuels"], list)
        for fuel in inv["fuels"]:
            assert fuel["fuel_class"] in ["solid", "gas", "liquid"]
            assert "sample_size" in fuel
        # Conditions must contain ranges in psi
        assert "conditions" in inv
        conds = inv["conditions"]
        assert conds["o2_percent"]["min"] <= conds["o2_percent"]["max"]
        assert conds["pressure_psi"]["min"] <= conds["pressure_psi"]["max"]
        assert isinstance(inv["sample"], bool)


def test_get_investigations_filter_gas(client):
    """GET /investigations?fuel_class=gas returns only investigations with gas fuels."""
    response = client.get("/investigations?fuel_class=gas")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    for inv in data:
        assert any(f["fuel_class"] == "gas" for f in inv["fuels"])


def test_get_investigations_filter_hardware(client):
    """GET /investigations?hardware=CIR-ACME matches case-insensitively."""
    response = client.get("/investigations?hardware=cir-acme")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    for inv in data:
        assert "cir-acme" == inv["hardware"].lower()


def test_get_investigations_overlap_range(client):
    """GET /investigations with range parameters checks OVERLAP."""
    # Saffire-II has o2_percent [21, 26], pressure_psi [10.2, 14.7]
    response = client.get("/investigations?o2_min=20&o2_max=22&pressure_min=10&pressure_max=12")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    names_lower = [inv["name"].lower() for inv in data]
    assert any("saffire-ii" in name for name in names_lower)


# ---------------------------------------------------------------------------
# Tests Endpoint (GET /tests)
# ---------------------------------------------------------------------------
def test_get_tests_raw_array(client):
    """GET /tests returns a raw JSON array TestRecord[]."""
    response = client.get("/tests")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0

    for t in data:
        assert "id" in t
        assert "investigation_id" in t
        assert "investigation_name" in t
        assert t["fuel_class"] in ["solid", "gas", "liquid"]
        assert t["flow_direction"] in ["opposed", "concurrent", "quiescent"]
        assert 0.0 <= t["o2_percent"] <= 100.0
        assert t["pressure_psi"] >= 0.0
        assert t["platform"] in ["iss", "drop_tower", "other"]
        assert isinstance(t["ended_early"], bool)
        assert isinstance(t["sample"], bool)
        # spread_rate is in mm/s or null
        if t["spread_rate"] is not None:
            assert t["spread_rate"] >= 0.0


def test_get_tests_moon_base_window(client):
    """GET /tests with Moon Base window (28-32% O2, 9.5-11 psi) checks INCLUSIVE WITHIN."""
    response = client.get("/tests?o2_min=28&o2_max=32&pressure_min=9.5&pressure_max=11")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    for t in data:
        assert 28.0 <= t["o2_percent"] <= 32.0
        assert 9.5 <= t["pressure_psi"] <= 11.0


def test_get_tests_fuel_class_separation(client):
    """GET /tests?fuel_class=solid vs gas."""
    solid_resp = client.get("/tests?fuel_class=solid")
    assert solid_resp.status_code == 200
    for t in solid_resp.json():
        assert t["fuel_class"] == "solid"

    gas_resp = client.get("/tests?fuel_class=gas")
    assert gas_resp.status_code == 200
    for t in gas_resp.json():
        assert t["fuel_class"] == "gas"


def test_get_tests_filter_by_investigation_id(client):
    """GET /tests?investigation_id=inv-bass-2 filters by parent ID."""
    response = client.get("/tests?investigation_id=inv-bass-2")
    assert response.status_code == 200
    for t in response.json():
        assert t["investigation_id"] == "inv-bass-2"


# ---------------------------------------------------------------------------
# Insights Endpoint (GET /insights)
# ---------------------------------------------------------------------------
def test_get_insights_raw_array_and_score_invariants(client):
    """GET /insights returns raw JSON array sorted strictly descending by score,

    with score == safety_impact * evidence_strength * mission_relevance.
    """
    response = client.get("/insights")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 5

    scores = [i["score"] for i in data]
    assert scores == sorted(scores, reverse=True)

    for i in data:
        assert i["risk_level"] in ["high", "medium", "low"]
        assert 1 <= i["safety_impact"] <= 5
        assert 1 <= i["evidence_strength"] <= 5
        assert 1 <= i["mission_relevance"] <= 5
        expected_score = i["safety_impact"] * i["evidence_strength"] * i["mission_relevance"]
        assert i["score"] == expected_score
        assert isinstance(i["reviewed"], bool)
        assert isinstance(i["sample"], bool)
        assert len(i["citations"]) >= 1


# ---------------------------------------------------------------------------
# CSV Export (GET /export/csv)
# ---------------------------------------------------------------------------
def test_export_csv_endpoint(client):
    """GET /export/csv must stream CSV starting with the exact hackathon header."""
    response = client.get("/export/csv?fuel_class=solid&o2_min=20")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "flamesight_per_test_v0.1_unverified.csv" in response.headers.get("content-disposition", "")

    csv_text = response.text
    # Required Hackathon header
    assert csv_text.startswith("# FlameSight Per-Test Dataset (v0.1, unverified extraction - NASA Space Apps 2026)")
    assert "test_id,investigation_id,investigation,fuel,fuel_class" in csv_text
    assert "dataset_status" in csv_text
    assert len(csv_text.splitlines()) > 5


# ---------------------------------------------------------------------------
# Secondary Endpoints
# ---------------------------------------------------------------------------
def test_secondary_endpoints(client):
    """Verify secondary aliases and helper endpoints."""
    # Aliases
    assert client.get("/api/investigations").status_code == 200
    assert client.get("/api/tests").status_code == 200
    assert client.get("/api/insights").status_code == 200
    assert client.get("/api/tests/export-csv").status_code == 200

    # Safety margins
    margins_resp = client.get("/api/safety-margins")
    assert margins_resp.status_code == 200
    assert len(margins_resp.json()) == 10

    # Habitat finder
    hab_resp = client.get("/api/coverage/habitat-finder?o2_percent=30.0&pressure_psi=10.2")
    assert hab_resp.status_code == 200
    assert len(hab_resp.json()) > 0


# ---------------------------------------------------------------------------
# Audit Unit Tests: SQLite Coercion & Upstream Normalization
# ---------------------------------------------------------------------------
def test_sqlite_helpers_audit():
    """Verify _to_bool and _parse_json_field accurately coerce SQLite values."""
    from app.db import _parse_json_field, _to_bool

    # Integer & string to bool coercion
    assert _to_bool(1) is True
    assert _to_bool(0) is False
    assert _to_bool("1") is True
    assert _to_bool("0") is False
    assert _to_bool("true") is True
    assert _to_bool("false") is False
    assert _to_bool(None, default=False) is False

    # JSON TEXT parsing
    assert _parse_json_field('["a", "b"]') == ["a", "b"]
    assert _parse_json_field('{"min": 10, "max": 20}') == {"min": 10, "max": 20}
    # Malformed JSON fallback to default
    assert _parse_json_field('{bad json', default=[]) == []


def test_ai_proxy_normalization_logic():
    """Verify that AskResponse validation and proxy normalization enforce contracts."""
    from app.schemas import AskResponse

    # Test that grounded=False forces answer="" and evidence=None
    resp = AskResponse(
        answer="Some text that should be erased",
        grounded=False,
        citations=[],
        evidence=None,
    )
    assert resp.answer == ""
    assert resp.grounded is False
    assert resp.evidence is None

