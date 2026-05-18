"""LLM 응답 집계 + 튜닝 제안 모듈 테스트."""
import json
from pathlib import Path

from engine.learner import aggregate


def _write_pair(results_dir: Path, llm_dir: Path, law_name: str,
                 findings: list[dict], llm_judgments: list[dict],
                 missed: list[dict] | None = None,
                 grade_opinion: str = "C", agree: bool = True):
    """결과+LLM 응답 한 쌍 작성."""
    result = {
        "law": {"law_id": "x", "name": law_name, "type": "법률",
                "law_category": "일반", "articles": []},
        "findings": findings,
        "article_scores": [],
        "category_scores": {},
        "law_score": 50.0,
        "law_grade": "D",
        "engine_version": "0.1.0",
    }
    (results_dir / f"{law_name}.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8")
    (llm_dir / f"{law_name}.json").write_text(json.dumps({
        "judgments": llm_judgments,
        "missed_findings": missed or [],
        "checklist": ["내부통제기준 갱신", "보고 양식 정비"],
        "overall_assessment": {"law_grade_opinion": grade_opinion,
                               "agree_with_engine": agree,
                               "comment": "test"},
    }, ensure_ascii=False), encoding="utf-8")


def _finding(fid: str, pattern: str, severity: str = "심각") -> dict:
    return {
        "finding_id": fid,
        "pattern_id": pattern,
        "pattern_name": pattern,
        "category": "거버넌스",
        "article_id": "art_1",
        "article_number": "제1조",
        "matched_text": "x",
        "severity": severity,
        "severity_score": 10,
        "summary": "x",
        "detection_method": "rule",
        "fix_type": None,
        "recommendation": {"template": "표준 권고"},
        "is_false_positive": False,
        "false_positive_reason": None,
    }


def test_aggregate_returns_error_when_no_responses(tmp_path):
    out = aggregate(
        results_dir=tmp_path / "r",
        llm_responses_dir=tmp_path / "l",
    )
    assert "error" in out


def test_aggregate_fp_rate_per_pattern(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    # 법령 A: G-04 후보 10건 중 8건 FP
    findings = [_finding(f"G04-{i:03d}", "G-04") for i in range(10)]
    judgments = (
        [{"finding_id": f"G04-{i:03d}", "verdict": "FP",
          "adjusted_severity": "양호", "reasoning": "기금 수탁기관이라 모법에 위임"}
         for i in range(8)]
        + [{"finding_id": f"G04-{i:03d}", "verdict": "TP",
           "adjusted_severity": "심각"} for i in range(8, 10)]
    )
    _write_pair(r, l, "법령A", findings, judgments)
    out = aggregate(results_dir=r, llm_responses_dir=l)
    ps = out["per_pattern_stats"]["G-04"]
    assert ps["total_candidates"] == 10
    assert ps["fp"] == 8
    assert ps["fp_rate"] == 0.8
    # FP rate ≥ 40% + n ≥ 10 → 필터 제안 생성
    assert any(p["pattern_id"] == "G-04" for p in out["fp_filter_proposals"])


def test_aggregate_severity_delta_threshold_proposal(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    # F-05 후보 12건 모두 심각→경고 (delta=-1)
    findings = [_finding(f"F05-{i:03d}", "F-05", "심각") for i in range(12)]
    judgments = [
        {"finding_id": f"F05-{i:03d}", "verdict": "TP", "adjusted_severity": "주의"}
        for i in range(12)
    ]
    _write_pair(r, l, "법령B", findings, judgments)
    out = aggregate(results_dir=r, llm_responses_dir=l)
    ps = out["per_pattern_stats"]["F-05"]
    assert ps["avg_severity_delta"] == -2.0  # 심각(4)→주의(2) = -2
    # |delta| ≥ 0.6 + n ≥ 10 → 임계치 제안
    assert any(p["pattern_id"] == "F-05" for p in out["threshold_proposals"])


def test_aggregate_collects_missed_and_new_pattern_proposals(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    findings = [_finding("F01-001", "F-01")]
    judgments = [{"finding_id": "F01-001", "verdict": "TP", "adjusted_severity": "경고"}]
    missed = [
        {"article_number": "제5조", "pattern_id": "S-03", "severity": "주의",
         "summary": "추가 모호표현"},
        {"article_number": "제10조", "pattern_id": "X-NEW", "name": "데이터주체권리",
         "severity": "경고", "summary": "개인정보 수집 정당화 부재"},
    ]
    _write_pair(r, l, "법령C", findings, judgments, missed=missed)
    out = aggregate(results_dir=r, llm_responses_dir=l)
    # S-03은 missed_patterns_top, X-NEW는 new_pattern_proposals
    assert any(p[0] == "S-03" for p in out["missed_patterns_top"])
    assert any(p["name"] == "데이터주체권리" for p in out["new_pattern_proposals"])


def test_aggregate_collects_improved_recommendations(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    findings = [_finding("G04-001", "G-04")]
    judgments = [{
        "finding_id": "G04-001", "verdict": "TP",
        "adjusted_severity": "심각",
        "improved_recommendation": "제22조 후단에 위험평가 절차를 호로 신설",
    }]
    _write_pair(r, l, "법령D", findings, judgments)
    out = aggregate(results_dir=r, llm_responses_dir=l)
    ps = out["per_pattern_stats"]["G-04"]
    assert ps["sample_improved_recs"]
    assert "위험평가" in ps["sample_improved_recs"][0]["improved"]


def test_aggregate_grade_opinion_distribution(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    findings = [_finding("X-001", "S-03")]
    judgments = [{"finding_id": "X-001", "verdict": "TP", "adjusted_severity": "주의"}]
    _write_pair(r, l, "법령E", findings, judgments, grade_opinion="C", agree=False)
    out = aggregate(results_dir=r, llm_responses_dir=l)
    # 엔진 D → LLM C 의견이 분포에 잡혀야
    assert "D→C" in out["grade_opinion_distribution"]
    # agree_with_engine=False도 카운트 (key는 bool 또는 stringified)
    agree = out["agree_with_engine"]
    false_count = agree.get(False, 0) + agree.get("false", 0) + agree.get("False", 0)
    assert false_count == 1


def test_aggregate_collects_checklist_frequency(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    findings = [_finding("X-001", "G-05")]
    judgments = [{"finding_id": "X-001", "verdict": "TP", "adjusted_severity": "경고"}]
    # 같은 체크리스트 항목이 여러 법령에 등장하면 빈도 ↑
    for name in ("법령F", "법령G", "법령H"):
        _write_pair(r, l, name, findings, judgments)
    out = aggregate(results_dir=r, llm_responses_dir=l)
    items = dict(out["frequent_checklist_items"])
    assert items.get("내부통제기준 갱신") == 3
