"""법제처 API fallback 단위 테스트 (네트워크 호출 없이 캐시·쿼터만)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.mcp.lawkr_api import LawKRClient


def test_lookup_returns_cached_response(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "테스트법": {"LawSearch": {"law": [{"법령명한글": "테스트법"}]}}
    }, ensure_ascii=False), encoding="utf-8")
    client = LawKRClient(cache_path=cache)
    payload = client.lookup("테스트법")
    assert payload is not None
    assert payload["LawSearch"]["law"][0]["법령명한글"] == "테스트법"
    # 쿼터는 캐시 히트 시 소비되지 않아야
    assert client.quota.used == 0


def test_check_article_returns_unknown_on_network_failure(tmp_path, monkeypatch):
    """_call이 None을 돌려주면 status=unknown."""
    cache = tmp_path / "cache.json"
    client = LawKRClient(cache_path=cache)
    monkeypatch.setattr(client, "_call", lambda law_name: None)
    res = client.check_article("미수록법", "1")
    assert res.status == "unknown"
    assert "법제처" in (res.note or "")


def test_check_article_handles_empty_law_list(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    client = LawKRClient(cache_path=cache)
    monkeypatch.setattr(
        client, "_call",
        lambda law_name: {"LawSearch": {"law": []}},
    )
    res = client.check_article("없는법", "1")
    assert res.status == "not_found"


def test_check_article_positive_result(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    client = LawKRClient(cache_path=cache)
    monkeypatch.setattr(
        client, "_call",
        lambda law_name: {"LawSearch": {"law": [{"법령명한글": "주택도시기금법"}]}},
    )
    res = client.check_article("주택도시기금법", "10")
    assert res.exists is True
    assert res.current_law_name == "주택도시기금법"


def test_quota_blocks_further_calls(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    client = LawKRClient(cache_path=cache, daily_limit=1)
    monkeypatch.setattr(
        client, "_call",
        lambda law_name: {"LawSearch": {"law": [{"법령명한글": "x"}]}},
    )
    # 한 번은 통과
    client.lookup("법1")
    assert client.quota.used == 1
    # _call이 호출되지 않도록 (쿼터 초과)
    monkeypatch.setattr(
        client, "_call", lambda law_name: pytest.fail("_call invoked after quota")
    )
    assert client.lookup("법2") is None
