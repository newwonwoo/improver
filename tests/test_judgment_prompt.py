"""프롬프트 모듈 + judgment_md 헤더 통합 + import_judgment 단위 테스트."""
import json
import subprocess
import sys
from pathlib import Path

from engine import cases, fpc, judgment_md, recommender, scorer
from engine.adapters import normalize_legalize_md
from engine.judgment_prompt import SYSTEM_PROMPT, expected_schema_excerpt, header
from engine.parser import parse_law
from engine.rules import run_all

REPO = Path(__file__).resolve().parent.parent
REAL_LAW = REPO / "data" / "laws" / "주택도시기금법.md"


def test_system_prompt_includes_six_tasks():
    """프롬프트가 6가지 작업 모두 지시하는지."""
    assert "TP/FP/BORDER" in SYSTEM_PROMPT
    assert "등급 재평가" in SYSTEM_PROMPT
    assert "권고안" in SYSTEM_PROMPT
    assert "미탐" in SYSTEM_PROMPT
    assert "체크리스트" in SYSTEM_PROMPT
    assert "종합 평가" in SYSTEM_PROMPT
    # JSON 단독 출력 강제
    assert "JSON" in SYSTEM_PROMPT
    assert "다른 텍스트" in SYSTEM_PROMPT or "마크다운" in SYSTEM_PROMPT


def test_system_prompt_lists_all_20_patterns():
    for p in ("S-01", "S-02", "F-04", "G-04", "L-03", "E-05"):
        assert p in SYSTEM_PROMPT


def test_system_prompt_specifies_fp_rules():
    """FP 기준에 FPC-02, FPC-04 등 명시."""
    assert "용어정의" in SYSTEM_PROMPT
    assert "벌칙" in SYSTEM_PROMPT
    assert "절차법" in SYSTEM_PROMPT
    assert "정책의무" in SYSTEM_PROMPT or "노력하여야" in SYSTEM_PROMPT


def test_header_has_system_prompt_block_and_meta():
    h = header("주택도시기금법", 108, 43)
    assert "주택도시기금법" in h
    assert "108" in h
    assert "43" in h
    assert "시스템 프롬프트" in h
    # 시스템 프롬프트가 코드블록에 박혀 있어야 그대로 복사 가능
    assert "```" in h


def test_expected_schema_excerpt_is_valid_example():
    """문서 하단의 예시 JSON이 실제로 파싱 가능해야."""
    text = expected_schema_excerpt()
    # ```json ... ``` 블록만 추출
    start = text.find("```json")
    end = text.find("```", start + 7)
    json_block = text[start + len("```json"):end].strip()
    parsed = json.loads(json_block)
    assert "judgments" in parsed
    assert "missed_findings" in parsed
    assert "checklist" in parsed
    assert "overall_assessment" in parsed


def test_judgment_md_includes_full_prompt():
    """렌더된 MD 안에 시스템 프롬프트와 응답 스키마가 모두 박혀 있어야."""
    text = REAL_LAW.read_text(encoding="utf-8")
    body, meta = normalize_legalize_md(text)
    law = parse_law(body, name="주택도시기금법", law_category="공공기관법")
    findings = fpc.correct(law, run_all(law))
    result = scorer.compute(law, findings)
    result = recommender.apply(result)
    result = cases.attach(result)
    md = judgment_md.render(result)
    assert "🤖 LLM 시스템 프롬프트" in md
    assert "TP/FP/BORDER" in md
    assert "🎯 응답 형식 재확인" in md
    assert "judgments" in md
    assert "위 JSON만 출력하세요" in md


# ── import_judgment.py 통합 ────────────────────────────────────


def test_import_judgment_applies_fp_and_severity(tmp_path):
    """LLM 응답 JSON → import → finding 갱신 + 점수 재계산."""
    # 1) 분석 결과 생성
    analysis_path = tmp_path / "analysis.json"
    subprocess.run([
        sys.executable, str(REPO / "scripts" / "analyze.py"),
        str(REAL_LAW), "--name", "주택도시기금법",
        "--category", "공공기관법",
        "--no-cross-pattern",
        "--output", str(analysis_path),
    ], check=True, capture_output=True)
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    # 첫 두 finding 골라서 응답 작성
    first = analysis["findings"][0]
    second = analysis["findings"][1] if len(analysis["findings"]) > 1 else first

    llm_response = {
        "judgments": [
            {
                "finding_id": first["finding_id"],
                "verdict": "FP",
                "adjusted_severity": "양호",
                "severity_changed": True,
                "reasoning": "용어정의 조문 — FPC-02 적용",
                "improved_recommendation": "",
            },
            {
                "finding_id": second["finding_id"],
                "verdict": "TP",
                "adjusted_severity": "경고",
                "severity_changed": True,
                "reasoning": "법령 특성 고려 시 1단계 하향이 적절",
                "improved_recommendation": "제2조 후단에 위임 범위를 호로 열거.",
                "reference": "법제처 입안길잡이 §23",
            },
        ],
        "missed_findings": [
            {
                "article_number": "제10조",
                "pattern_id": "E-01",
                "severity": "주의",
                "summary": "조건 중첩 추가 식별",
                "recommendation": "조건 구조 단순화.",
            },
        ],
        "checklist": ["내부통제기준서 갱신", "보고 양식 정비"],
        "overall_assessment": {
            "law_grade_opinion": "D",
            "agree_with_engine": False,
            "comment": "F는 과도, D가 적정.",
        },
    }
    response_path = tmp_path / "llm.json"
    response_path.write_text(json.dumps(llm_response, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "result_with_llm.json"

    proc = subprocess.run([
        sys.executable, str(REPO / "scripts" / "import_judgment.py"),
        str(analysis_path),
        "--llm-response", str(response_path),
        "--output", str(out_path),
    ], capture_output=True, text=True, check=True)
    assert "applied=2" in proc.stderr
    assert "missed_added=1" in proc.stderr

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["llm_review"]["fp_marked"] == 1
    assert payload["llm_review"]["severity_changed"] >= 1
    assert payload["llm_review"]["missed_findings_added"] == 1
    assert payload["llm_review"]["checklist"] == ["내부통제기준서 갱신", "보고 양식 정비"]
    assert payload["llm_review"]["overall_assessment"]["law_grade_opinion"] == "D"
    # 첫 finding은 양호로 내려가고 FP 마킹
    by_id = {f["finding_id"]: f for f in payload["findings"]}
    assert by_id[first["finding_id"]]["is_false_positive"] is True
    assert by_id[first["finding_id"]]["severity"] == "양호"
    # 미탐 추가
    miss_ids = [f["finding_id"] for f in payload["findings"]
                if f["finding_id"].startswith("LLM-MISS")]
    assert miss_ids
