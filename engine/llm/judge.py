"""LLM 정밀 판단 — F-04/F-05/E-05 룰 후보의 등급/오탐 재판정.

설계서 §4.2 + §4.4 응답 검증.
"""
from __future__ import annotations

from ..schema import AnalysisResult, Finding
from ..severity import SEVERITY_ORDER, score_of
from .client import LLMClient, make_default_client
from .prompts import SYSTEM_FOR_PATTERN, format_judgment_user

_JUDGED_PATTERNS = {"F-04", "F-05", "E-05"}
_KEY_PER_PATTERN = {
    "F-04": "is_deemed_consent",
    "F-05": "is_arbitrary_discretion",
    "E-05": "has_sanction_gap",
}


def _severity_delta(old: str, new: str) -> int:
    return SEVERITY_ORDER.index(new) - SEVERITY_ORDER.index(old)


def judge_findings(
    result: AnalysisResult, *, client: LLMClient | None = None, article_lookup=None
) -> AnalysisResult:
    """결과의 F-04/F-05/E-05 finding에 LLM 정밀 판단을 적용."""
    if not any(f.pattern_id in _JUDGED_PATTERNS for f in result.findings):
        return result
    client = client or make_default_client()
    by_id = article_lookup or {a.article_id: a for a in result.law.articles}

    for f in result.findings:
        if f.pattern_id not in _JUDGED_PATTERNS:
            continue
        if f.severity not in {"심각", "경고", "주의"}:
            continue
        system = SYSTEM_FOR_PATTERN[f.pattern_id]
        article = by_id.get(f.article_id)
        article_text = article.full_text if article else ""
        user = format_judgment_user(result.law.name, article_text, f.matched_text)
        response = client.call(system=system, user=user)
        parsed = response.parsed
        if not parsed:
            continue

        # 오탐 처리
        positive_key = _KEY_PER_PATTERN[f.pattern_id]
        if parsed.get(positive_key) is False:
            f.is_false_positive = True
            f.false_positive_reason = parsed.get("reasoning") or "LLM 부정 판정"
            f.severity = "양호"
            f.severity_score = 0
            f.detection_method = "rule+llm"
            continue

        new_severity = parsed.get("severity")
        if new_severity in SEVERITY_ORDER:
            delta = _severity_delta(f.severity, new_severity)
            # §4.4 응답 검증: 2단계↑ 변경은 플래그만 (적용은 보수적)
            if abs(delta) >= 2:
                f.recommendation = {**f.recommendation, "human_review_needed": True,
                                    "llm_proposed_severity": new_severity}
            else:
                f.severity = new_severity
                f.severity_score = score_of(new_severity)
            f.detection_method = "rule+llm"
            if parsed.get("severity_basis"):
                f.summary = f"{f.summary} | LLM: {parsed['severity_basis']}"
    return result
