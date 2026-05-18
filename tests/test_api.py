"""FastAPI HTTP 엔드포인트 단위 테스트 (fastapi 미설치 시 스킵)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

from fastapi.testclient import TestClient  # noqa: E402

from engine.api import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_patterns_endpoint_lists_rules(client):
    res = client.get("/patterns")
    assert res.status_code == 200
    ids = {p["id"] for p in res.json()["patterns"]}
    assert "G-04" in ids
    assert "S-03" in ids


def test_agencies_endpoint_returns_mapping(client):
    res = client.get("/agencies")
    assert res.status_code == 200
    data = res.json()
    assert "G-04-b" in data


def test_analyze_endpoint(client):
    payload = {
        "name": "주택도시기금법",
        "text": "제22조(업무지침) 수탁기관은 업무지침을 정하여야 한다.",
        "category": "공공기관법",
    }
    res = client.post("/analyze", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["law_grade"] in {"A", "B", "C", "D", "F"}
    assert any(f["pattern_id"] == "G-04" for f in body["findings"])


def test_analyze_rejects_empty_text(client):
    res = client.post("/analyze", json={"name": "x", "text": "   "})
    assert res.status_code == 400
