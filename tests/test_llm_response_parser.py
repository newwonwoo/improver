"""웹 UI LLM 응답에서 JSON 추출 + 스키마 검증 테스트."""
import json

from engine.llm_response_parser import (
    extract_json_from_llm_text,
    parse_llm_response,
    validate_and_normalize,
)


def test_extract_fenced_json():
    text = """좋은 분석이네요. 다음과 같이 판정합니다:

```json
{"judgments": [{"finding_id": "G-04-001", "verdict": "TP"}]}
```

추가 의견 있으면 알려주세요."""
    ex = extract_json_from_llm_text(text)
    assert ex.parsed is not None
    assert ex.method == "fenced_json"
    assert ex.parsed["judgments"][0]["finding_id"] == "G-04-001"


def test_extract_fenced_no_lang_tag():
    text = "```\n{\"judgments\": [{\"finding_id\": \"x\", \"verdict\": \"FP\"}]}\n```"
    ex = extract_json_from_llm_text(text)
    assert ex.parsed is not None
    assert ex.parsed["judgments"][0]["verdict"] == "FP"


def test_extract_raw_json():
    text = '{"judgments": [{"finding_id": "x", "verdict": "TP"}]}'
    ex = extract_json_from_llm_text(text)
    assert ex.parsed is not None


def test_extract_with_leading_text_and_braces():
    text = "Here is the JSON: {\"judgments\": [{\"finding_id\":\"x\",\"verdict\":\"TP\"}]} 끝."
    ex = extract_json_from_llm_text(text)
    assert ex.parsed is not None
    assert ex.method == "balanced_braces"


def test_trailing_comma_recovered():
    text = '{"judgments": [{"finding_id": "x", "verdict": "TP",}],}'
    ex = extract_json_from_llm_text(text)
    assert ex.parsed is not None


def test_balanced_braces_with_string_containing_braces():
    text = 'pre {"judgments": [{"finding_id": "x", "verdict": "TP", "reasoning": "그러나 {조건}이 충족"}]} post'
    ex = extract_json_from_llm_text(text)
    assert ex.parsed is not None
    assert "그러나" in ex.parsed["judgments"][0]["reasoning"]


def test_empty_or_garbage_returns_error():
    ex = extract_json_from_llm_text("")
    assert ex.parsed is None
    ex2 = extract_json_from_llm_text("죄송합니다, JSON을 만들 수 없습니다.")
    assert ex2.parsed is None


# ── 스키마 검증 ─────────────────────────────────────────────


def test_validate_normalizes_dict_to_list():
    parsed = {"judgments": {"finding_id": "x", "verdict": "TP"}}
    res = validate_and_normalize(parsed)
    assert res.valid is True
    assert res.auto_fixed is True
    assert isinstance(parsed["judgments"], list)


def test_validate_verdict_case_normalization():
    parsed = {"judgments": [{"finding_id": "x", "verdict": "tp"}]}
    res = validate_and_normalize(parsed)
    assert parsed["judgments"][0]["verdict"] == "TP"
    assert res.auto_fixed is True


def test_validate_severity_english_to_korean():
    parsed = {"judgments": [
        {"finding_id": "x", "verdict": "TP", "adjusted_severity": "Critical"}
    ]}
    res = validate_and_normalize(parsed)
    assert parsed["judgments"][0]["adjusted_severity"] == "심각"
    assert res.auto_fixed is True


def test_validate_missing_required_judgment_keys():
    parsed = {"judgments": [{"verdict": "TP"}]}  # finding_id 누락
    res = validate_and_normalize(parsed)
    assert res.valid is False
    assert any("finding_id" in e for e in res.errors)


def test_validate_optional_fields_default():
    parsed = {"judgments": [{"finding_id": "x", "verdict": "TP"}]}
    validate_and_normalize(parsed)
    assert parsed["missed_findings"] == []
    assert parsed["checklist"] == []


def test_validate_checklist_string_to_list():
    parsed = {
        "judgments": [{"finding_id": "x", "verdict": "TP"}],
        "checklist": "내부통제기준 갱신",
    }
    validate_and_normalize(parsed)
    assert parsed["checklist"] == ["내부통제기준 갱신"]


def test_parse_llm_response_end_to_end():
    text = """LLM 응답입니다:

```json
{
  "judgments": [
    {"finding_id": "G-04-001", "verdict": "TP", "adjusted_severity": "심각",
     "reasoning": "5요소 모두 빠짐."}
  ],
  "missed_findings": [],
  "checklist": ["내부통제기준서 작성"]
}
```
"""
    ex, val = parse_llm_response(text)
    assert ex.parsed is not None
    assert val.valid is True
