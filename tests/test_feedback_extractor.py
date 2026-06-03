"""사례·템플릿 후보 자동 추출 테스트."""
import json
from pathlib import Path

from engine.feedback_extractor import (
    extract_case_candidates,
    extract_template_candidates,
    export_proposals,
)


def _write_pair(results_dir: Path, llm_dir: Path, law_name: str,
                 finding: dict, judgment_overrides: dict | None = None,
                 missed: list[dict] | None = None):
    """결과 + 응답 한 쌍 생성. finding 1개 + 그에 대한 judgment 1개."""
    result = {
        "law": {"law_id": "x", "name": law_name, "type": "법률",
                "law_category": "공공기관법", "articles": []},
        "findings": [finding],
        "article_scores": [], "category_scores": {},
        "law_score": 0.0, "law_grade": "F", "engine_version": "0.1.0",
    }
    (results_dir / f"{law_name}.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8")
    judgment = {
        "finding_id": finding["finding_id"], "verdict": "TP",
        "adjusted_severity": "심각",
        **(judgment_overrides or {}),
    }
    (llm_dir / f"{law_name}.json").write_text(json.dumps({
        "judgments": [judgment],
        "missed_findings": missed or [],
    }, ensure_ascii=False), encoding="utf-8")


def _finding(fid: str, pid: str, template: str = "표준 권고") -> dict:
    return {
        "finding_id": fid, "pattern_id": pid, "pattern_name": pid,
        "category": "거버넌스", "article_id": "art_22",
        "article_number": "제22조", "matched_text": "x",
        "severity": "심각", "severity_score": 10, "summary": "x",
        "detection_method": "rule", "fix_type": None,
        "recommendation": {"template": template, "sub_check_id": f"{pid}-a"},
        "is_false_positive": False, "false_positive_reason": None,
    }


# ── 사례 추출 ──────────────────────────────────────────────


def test_extract_case_with_agency_and_url(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    _write_pair(r, l, "법령A", _finding("G04-001", "G-04"), {
        "reference": "감사원 2024.6 한국토지주택공사 개선요구. https://www.bai.go.kr/case/123",
        "reasoning": "기금 위탁운용 내부통제 미흡",
    })
    cases = extract_case_candidates(results_dir=r, llm_dir=l)
    assert len(cases) == 1
    c = list(cases.values())[0]
    assert c.agency == "감사원"
    assert c.date == "2024-06"
    assert c.url == "https://www.bai.go.kr/case/123"
    assert "G-04" in c.related_patterns
    assert "G-04-a" in c.related_sub_checks


def test_extract_case_deduplicates_same_agency_date_summary(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    for name in ("법령A", "법령B", "법령C"):
        _write_pair(r, l, name, _finding("G04-001", "G-04"), {
            "reference": "감사원 2024.6 같은 사례입니다.",
            "improved_recommendation": "동일한 권고 텍스트",
        })
    cases = extract_case_candidates(results_dir=r, llm_dir=l)
    assert len(cases) == 1
    c = list(cases.values())[0]
    assert c.occurrences == 3


def test_extract_case_skips_when_no_agency(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    _write_pair(r, l, "법령A", _finding("G04-001", "G-04"), {
        "reference": "그냥 자유 텍스트",
    })
    cases = extract_case_candidates(results_dir=r, llm_dir=l)
    assert cases == {}


def test_extract_case_from_missed_findings(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    _write_pair(r, l, "법령A", _finding("G04-001", "G-04"),
                 missed=[{
                     "article_number": "제15조",
                     "pattern_id": "F-03",
                     "severity": "경고",
                     "summary": "처분 + 청문 부재",
                     "reference": "공정위 2023.4 사건",
                 }])
    cases = extract_case_candidates(results_dir=r, llm_dir=l)
    assert any(c.agency == "공정위" for c in cases.values())


# ── 템플릿 추출 ─────────────────────────────────────────────


def test_template_candidate_emitted_when_consistent(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    # 같은 (G-04, 심각)에 대해 3개 법령에서 비슷한 권고
    rec = "제22조 후단에 위험평가·통제활동·모니터링 절차를 호로 신설하라."
    for name in ("법령A", "법령B", "법령C"):
        _write_pair(r, l, name, _finding("G04-001", "G-04"), {
            "improved_recommendation": rec,
        })
    templates = extract_template_candidates(
        results_dir=r, llm_dir=l,
        current_templates={"G-04": {"심각": "내부통제 의무 자체가 부재..."}},
    )
    assert "G-04/심각" in templates
    t = templates["G-04/심각"]
    assert t.occurrences == 3
    assert t.diverges_from_current is True
    assert "위험평가" in t.suggested_template


def test_template_not_emitted_when_below_min_occurrences(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    _write_pair(r, l, "법령A", _finding("G04-001", "G-04"), {
        "improved_recommendation": "한 번만 나온 권고 텍스트입니다.",
    })
    templates = extract_template_candidates(results_dir=r, llm_dir=l)
    assert templates == {}


def test_template_skips_fp_verdicts(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    for name in ("A", "B", "C"):
        _write_pair(r, l, name, _finding("G04-001", "G-04"), {
            "verdict": "FP",
            "improved_recommendation": "FP라 권고 무시되어야",
        })
    templates = extract_template_candidates(results_dir=r, llm_dir=l)
    assert templates == {}


# ── 통합 export ─────────────────────────────────────────────


def test_export_proposals_writes_files(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    l = tmp_path / "l"; l.mkdir()
    out = tmp_path / "feedback"
    _write_pair(r, l, "법령A", _finding("G04-001", "G-04"), {
        "reference": "감사원 2024.6 사례",
        "improved_recommendation": "제22조 후단에 5요소 신설",
    })
    stats = export_proposals(
        results_dir=r, llm_dir=l, output_dir=out,
        current_recommendations_path=None,
    )
    assert (out / "case_candidates.json").exists()
    assert (out / "template_candidates.json").exists()
    assert stats["cases"] >= 1
