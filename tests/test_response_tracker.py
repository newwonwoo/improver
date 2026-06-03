"""응답 추적 모듈 테스트."""
import json

from engine.response_tracker import (
    LawStatus,
    latest_response_path,
    scan,
    summarize,
    write_index,
)


def test_scan_marks_pending_and_processed(tmp_path):
    j = tmp_path / "judgments"; j.mkdir()
    r = tmp_path / "responses"; r.mkdir()
    (j / "법령A.md").write_text("# A", encoding="utf-8")
    (j / "법령B.md").write_text("# B", encoding="utf-8")
    (j / "법령C.md").write_text("# C", encoding="utf-8")
    # 법령A: 응답 있음
    (r / "법령A.json").write_text(json.dumps({
        "judgments": [{"finding_id": "x", "verdict": "TP"}],
        "missed_findings": [{"article_number": "제5조", "pattern_id": "S-03"}],
        "overall_assessment": {"law_grade_opinion": "C"},
    }), encoding="utf-8")

    status = scan(judgments_dir=j, responses_dir=r)
    assert status["법령A"].is_processed
    assert status["법령A"].judgments_count == 1
    assert status["법령A"].missed_count == 1
    assert status["법령A"].has_overall
    assert not status["법령B"].is_processed
    assert not status["법령C"].is_processed


def test_scan_detects_duplicates(tmp_path):
    j = tmp_path / "j"; j.mkdir()
    r = tmp_path / "r"; r.mkdir()
    (j / "법령A.md").write_text("# A", encoding="utf-8")
    (r / "법령A.json").write_text('{"judgments": []}', encoding="utf-8")
    (r / "법령A__2026-05-01.json").write_text('{"judgments": []}', encoding="utf-8")

    status = scan(judgments_dir=j, responses_dir=r)
    assert status["법령A"].has_duplicate_responses
    assert len(status["법령A"].response_files) == 2


def test_scan_records_parse_errors(tmp_path):
    j = tmp_path / "j"; j.mkdir()
    r = tmp_path / "r"; r.mkdir()
    (j / "법령A.md").write_text("# A", encoding="utf-8")
    (r / "법령A.json").write_text("이거 JSON 아님", encoding="utf-8")

    status = scan(judgments_dir=j, responses_dir=r)
    assert status["법령A"].parse_errors
    assert not status["법령A"].is_processed


def test_summarize_progress(tmp_path):
    j = tmp_path / "j"; j.mkdir()
    r = tmp_path / "r"; r.mkdir()
    for n in ("A", "B", "C", "D"):
        (j / f"법령{n}.md").write_text("x", encoding="utf-8")
    (r / "법령A.json").write_text('{"judgments": []}', encoding="utf-8")

    status = scan(judgments_dir=j, responses_dir=r)
    summary = summarize(status)
    assert summary["total_known"] == 4
    assert summary["has_judgment_md"] == 4
    assert summary["processed"] == 1
    assert summary["pending_count"] == 3
    assert summary["progress_rate"] == 0.25


def test_write_index_format(tmp_path):
    j = tmp_path / "j"; j.mkdir()
    r = tmp_path / "r"; r.mkdir()
    (j / "법령A.md").write_text("x", encoding="utf-8")
    status = scan(judgments_dir=j, responses_dir=r)
    idx_path = r / "_index.json"
    write_index(status, idx_path)
    payload = json.loads(idx_path.read_text(encoding="utf-8"))
    assert "summary" in payload and "laws" in payload
    assert payload["summary"]["pending_count"] == 1


def test_latest_response_path_picks_newest(tmp_path):
    import time
    r = tmp_path / "r"; r.mkdir()
    f1 = r / "법령A.json"
    f1.write_text("{}", encoding="utf-8")
    time.sleep(0.05)
    f2 = r / "법령A__2026-06-01.json"
    f2.write_text("{}", encoding="utf-8")
    latest = latest_response_path("법령A", r)
    assert latest == f2


def test_scan_ignores_index_file(tmp_path):
    j = tmp_path / "j"; j.mkdir()
    r = tmp_path / "r"; r.mkdir()
    (j / "법령A.md").write_text("x", encoding="utf-8")
    (r / "_index.json").write_text('{"meta": "true"}', encoding="utf-8")
    status = scan(judgments_dir=j, responses_dir=r)
    # _index.json은 법령으로 잡히면 안 됨
    assert "_index" not in status
