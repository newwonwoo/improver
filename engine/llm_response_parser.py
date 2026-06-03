"""LLM 웹 UI 응답에서 JSON 추출 — 마크다운/설명문이 섞여도 동작.

웹 UI(ChatGPT/Gemini) 응답 흔한 패턴:
1. ```json\\n{...}\\n``` 코드블록
2. "Here is the JSON response:\\n{...}\\n다음과 같습니다."
3. 코드블록 없이 그냥 본문에 JSON
4. trailing comma (LLM이 자주 만듦)
5. 작은 따옴표 사용 (드물지만)
6. 응답 앞뒤 인사말 + 후기

extract_json_from_llm_text()는 가능한 모든 경우에서 JSON 객체를 찾아 dict 반환.
실패 시 None + 상세 reason.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


_FENCED_JSON = re.compile(r"```(?:json|JSON)?\s*\n(.*?)\n```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


@dataclass
class ExtractResult:
    parsed: dict[str, Any] | None
    raw_snippet: str | None
    method: str   # fenced_json | first_braces | balanced_braces | raw
    error: str | None = None


def _strip_trailing_commas(s: str) -> str:
    return _TRAILING_COMMA.sub(r"\1", s)


def _try_parse(snippet: str) -> dict[str, Any] | None:
    try:
        out = json.loads(snippet)
    except json.JSONDecodeError:
        try:
            out = json.loads(_strip_trailing_commas(snippet))
        except json.JSONDecodeError:
            return None
    return out if isinstance(out, dict) else None


def _balanced_object(text: str, start: int) -> str | None:
    """text[start]가 '{' 일 때, 균형 잡힌 객체 끝 위치까지 잘라 반환.

    문자열 안의 중괄호는 무시. 이스케이프된 따옴표도 처리.
    """
    if start < 0 or start >= len(text) or text[start] != "{":
        return None
    depth = 0
    i = start
    in_string = False
    escape = False
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if c == "\\":
            escape = True
            i += 1
            continue
        if c == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]
        i += 1
    return None


def extract_json_from_llm_text(text: str) -> ExtractResult:
    """LLM 응답 문자열에서 JSON 객체 추출."""
    if not text or not text.strip():
        return ExtractResult(None, None, "raw", "empty input")

    text = text.strip()

    # 1. 코드 펜스 우선 — ```json ... ``` 또는 ``` ... ```
    for m in _FENCED_JSON.finditer(text):
        candidate = m.group(1).strip()
        # 그 안에서 첫 { 찾기 (코드블록이 설명문일 수도)
        brace = candidate.find("{")
        if brace != -1:
            obj = _balanced_object(candidate, brace) or candidate[brace:]
            parsed = _try_parse(obj)
            if parsed is not None:
                return ExtractResult(parsed, obj, "fenced_json")

    # 2. 첫 '{' 부터 균형 잡힌 객체 찾기
    first_brace = text.find("{")
    if first_brace != -1:
        obj = _balanced_object(text, first_brace)
        if obj:
            parsed = _try_parse(obj)
            if parsed is not None:
                return ExtractResult(parsed, obj, "balanced_braces")
            # 균형 잡힌 객체는 찾았지만 파싱 실패 → trailing comma 시도 이미 했음

    # 3. 마지막 시도: 전체 텍스트
    parsed = _try_parse(text)
    if parsed is not None:
        return ExtractResult(parsed, text, "raw")

    return ExtractResult(
        None, None, "raw",
        f"JSON 추출 실패 — 텍스트 시작 100자: {text[:100]!r}",
    )


# ── 스키마 검증 ─────────────────────────────────────────────────


_REQUIRED_TOP_LEVEL = {"judgments"}
_OPTIONAL_TOP_LEVEL = {"missed_findings", "checklist", "overall_assessment"}
_REQUIRED_JUDGMENT = {"finding_id", "verdict"}
_VALID_VERDICTS = {"TP", "FP", "BORDER"}
_VALID_SEVERITIES = {"심각", "경고", "주의", "개선", "양호"}


@dataclass
class ValidationResult:
    valid: bool
    warnings: list[str]
    errors: list[str]
    auto_fixed: bool = False


def validate_and_normalize(parsed: dict[str, Any]) -> ValidationResult:
    """파싱된 dict가 우리 스키마에 부합하는지 검증 + 가벼운 정규화.

    - judgments가 dict (단일 항목)이면 list로 감싸기
    - verdict 대소문자 정규화
    - severity 영문이면 한글로 매핑
    - 필수 필드 누락은 errors, 가벼운 문제는 warnings
    """
    warnings: list[str] = []
    errors: list[str] = []
    auto_fixed = False

    if not isinstance(parsed, dict):
        return ValidationResult(False, [], [f"최상위가 dict가 아님: {type(parsed).__name__}"])

    missing = _REQUIRED_TOP_LEVEL - set(parsed.keys())
    if missing:
        errors.append(f"필수 키 누락: {missing}")

    # judgments 정규화
    judgments = parsed.get("judgments")
    if isinstance(judgments, dict):
        parsed["judgments"] = [judgments]
        judgments = parsed["judgments"]
        warnings.append("judgments가 단일 dict → list로 변환")
        auto_fixed = True
    elif judgments is None:
        parsed["judgments"] = []
        warnings.append("judgments 누락 → 빈 list로")
        auto_fixed = True

    sev_en_to_kr = {
        "critical": "심각", "warning": "경고",
        "caution": "주의", "minor": "개선", "good": "양호",
    }

    for i, j in enumerate(parsed.get("judgments", [])):
        if not isinstance(j, dict):
            errors.append(f"judgments[{i}]가 dict가 아님")
            continue
        missing_j = _REQUIRED_JUDGMENT - set(j.keys())
        if missing_j:
            errors.append(f"judgments[{i}] 필수 키 누락: {missing_j}")

        # verdict 정규화
        v = j.get("verdict")
        if isinstance(v, str):
            v_upper = v.strip().upper()
            if v_upper in _VALID_VERDICTS and v != v_upper:
                j["verdict"] = v_upper
                auto_fixed = True
            elif v_upper not in _VALID_VERDICTS:
                warnings.append(f"judgments[{i}] 알 수 없는 verdict: {v}")

        # severity 한글 매핑
        sev = j.get("adjusted_severity")
        if isinstance(sev, str):
            key = sev.strip().lower()
            if key in sev_en_to_kr:
                j["adjusted_severity"] = sev_en_to_kr[key]
                auto_fixed = True
            elif sev not in _VALID_SEVERITIES:
                warnings.append(f"judgments[{i}] 알 수 없는 severity: {sev}")

    # missed_findings 정규화
    missed = parsed.get("missed_findings")
    if missed is None:
        parsed["missed_findings"] = []
    elif isinstance(missed, dict):
        parsed["missed_findings"] = [missed]
        auto_fixed = True

    # checklist 정규화
    checklist = parsed.get("checklist")
    if checklist is None:
        parsed["checklist"] = []
    elif isinstance(checklist, str):
        parsed["checklist"] = [checklist]
        auto_fixed = True

    return ValidationResult(
        valid=not errors,
        warnings=warnings,
        errors=errors,
        auto_fixed=auto_fixed,
    )


def parse_llm_response(text: str) -> tuple[ExtractResult, ValidationResult]:
    """one-shot 헬퍼: extract + validate."""
    ex = extract_json_from_llm_text(text)
    if ex.parsed is None:
        return ex, ValidationResult(False, [], ["JSON 추출 실패"])
    val = validate_and_normalize(ex.parsed)
    return ex, val
