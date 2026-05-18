"""LLM 호출 로그 보존 단위 테스트."""
import json

from engine.llm import MockClient, dump_log


def test_mock_client_records_log_entry():
    mock = MockClient(default={"severity": "경고", "reasoning": "x", "severity_basis": "y"})
    mock.call(system="sys A", user="user message 1")
    mock.call(system="sys A", user="user message 2")
    assert len(mock.log) == 2
    assert mock.log[0].system_hash == mock.log[1].system_hash
    assert mock.log[0].duration_ms >= 0


def test_dump_log_writes_jsonl(tmp_path):
    mock = MockClient(default={"severity": "주의", "reasoning": "x", "severity_basis": "y"})
    mock.call(system="sys", user="user A")
    mock.call(system="sys", user="user B")
    path = tmp_path / "llm_log.jsonl"
    written = dump_log(mock, path)
    assert written == 2
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["model"] == "mock"
    assert "system_hash" in rec
    assert rec["parsed"]["severity"] == "주의"


def test_log_entries_have_distinct_timestamps_or_durations(tmp_path):
    """duration_ms는 항상 ≥ 0, timestamp는 형식이 ISO."""
    mock = MockClient(default={"x": 1})
    mock.call(system="s", user="u")
    entry = mock.log[0]
    assert entry.duration_ms >= 0
    assert "T" in entry.timestamp  # ISO 형식
