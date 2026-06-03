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
    # G-04 requires: 5+ articles, applicable law name (기금 matches), AND
    # explicit internal-control signal in body (R1 — no single-keyword fire).
    text = "\n".join([
        "제1조(목적) 이 법은 주택도시기금의 설치 및 운영에 관하여 필요한 사항을 규정함을 목적으로 한다.",
        "제2조(정의) 이 법에서 \"기금\"이란 주택도시기금을 말한다.",
        "제10조(기금의 조성) 기금은 다음 각 호의 재원으로 조성한다.",
        "제15조(기금의 운용) 기금관리주체는 기금을 운용한다.",
        "제20조(수탁기관의 지정) 국토교통부장관은 수탁기관을 지정할 수 있다.",
        "제22조(업무지침) 수탁기관은 업무지침을 정하여야 한다. 다만, 준법감시인은 두지 아니한다.",
        "제30조(감독) 국토교통부장관은 기금관리주체를 감독한다.",
    ])
    payload = {
        "name": "주택도시기금법",
        "text": text,
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
