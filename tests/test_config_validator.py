"""config 무결성 검증 테스트."""
import json
from pathlib import Path

from engine.config_validator import (
    validate_all,
    validate_cases,
    validate_patterns,
    validate_recommendations,
    validate_sub_check_agencies,
)


def _write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_recommendations_complete_passes(tmp_path):
    p = tmp_path / "recs.json"
    _write(p, {
        "S-03": {sev: f"권고 {sev}" * 3 for sev in
                  ("심각", "경고", "주의", "개선", "양호")},
    })
    r = validate_recommendations(p)
    assert r.ok
    assert not r.warnings


def test_recommendations_missing_severity_warns(tmp_path):
    p = tmp_path / "recs.json"
    _write(p, {"S-03": {"심각": "권고 텍스트 길어요"}})  # 4개 누락
    r = validate_recommendations(p)
    assert r.ok  # 에러는 아님
    assert any("등급 누락" in w for w in r.warnings)


def test_recommendations_unknown_pattern_warns(tmp_path):
    p = tmp_path / "recs.json"
    _write(p, {"Z-99": {"심각": "x" * 20, "경고": "y" * 20, "주의": "z" * 20,
                          "개선": "x" * 20, "양호": "x" * 20}})
    r = validate_recommendations(p)
    assert any("Z-99" in w for w in r.warnings)


def test_cases_duplicate_id_is_error(tmp_path):
    p = tmp_path / "cases.json"
    _write(p, {"cases": [
        {"case_id": "X-001", "agency": "감사원", "summary": "x"},
        {"case_id": "X-001", "agency": "감사원", "summary": "y"},
    ]})
    r = validate_cases(p)
    assert not r.ok
    assert any("중복" in e for e in r.errors)


def test_cases_missing_required_field_is_error(tmp_path):
    p = tmp_path / "cases.json"
    _write(p, {"cases": [{"case_id": "X-001"}]})  # agency, summary 누락
    r = validate_cases(p)
    assert not r.ok


def test_cases_unknown_agency_warns(tmp_path):
    p = tmp_path / "cases.json"
    _write(p, {"cases": [
        {"case_id": "X-001", "agency": "유령기관", "summary": "x"}
    ]})
    r = validate_cases(p)
    assert any("유령기관" in w for w in r.warnings)


def test_sub_check_format_warning(tmp_path):
    p = tmp_path / "sub.json"
    _write(p, {"G04b": ["감사원"]})  # 형식 비표준
    r = validate_sub_check_agencies(p)
    assert any("형식" in w for w in r.warnings)


def test_patterns_unknown_pattern_warns(tmp_path):
    p = tmp_path / "patterns.json"
    _write(p, {"Z-99": {"enabled": True}})
    r = validate_patterns(p)
    assert any("Z-99" in w for w in r.warnings)


def test_actual_repo_config_validates(tmp_path):
    """본 레포의 config 디렉토리 무결성 회귀 방지."""
    import os
    repo_config = Path(__file__).resolve().parent.parent / "config"
    if not repo_config.exists():
        return  # skip
    reports = validate_all(repo_config)
    # 에러는 0이어야 (경고는 허용)
    errors = [(r.file, e) for r in reports for e in r.errors]
    assert not errors, f"config 무결성 에러: {errors}"
