"""Layer 3 맞춤 권고안 — 심각·경고 finding 대상.

설계서 §2.5: LLM 호출 대상 선별 + 비용 통제.
주의 등급은 패턴별 첫 1건만 LLM, 나머지는 Layer 1 템플릿 유지.
"""
from __future__ import annotations

from collections import defaultdict

from ..schema import AnalysisResult, Finding
from ..severity import SEVERITY_ORDER, score_of
from .client import LLMClient, make_default_client
from .prompts import RECOMMENDATION_SYSTEM, format_recommendation_user


def _should_call(f: Finding, seen_caution_patterns: set[str]) -> bool:
    if f.is_false_positive:
        return False
    if f.severity in {"심각", "경고"}:
        return True
    if f.severity == "주의" and f.pattern_id not in seen_caution_patterns:
        seen_caution_patterns.add(f.pattern_id)
        return True
    return False


def generate_recommendations(
    result: AnalysisResult, *, client: LLMClient | None = None,
    max_calls: int = 80,
) -> AnalysisResult:
    """결과의 심각·경고 finding에 Layer 3 맞춤 권고안을 부착."""
    client = client or make_default_client()
    by_id = {a.article_id: a for a in result.law.articles}
    seen_caution: set[str] = set()
    calls = 0
    for f in result.findings:
        if calls >= max_calls:
            break
        if not _should_call(f, seen_caution):
            continue
        template = (f.recommendation or {}).get("template", "")
        article = by_id.get(f.article_id)
        article_text = article.full_text if article else ""
        user = format_recommendation_user(
            result.law.name,
            article_text,
            f.pattern_id,
            f.pattern_name,
            f.severity,
            template,
            reference=(f.recommendation or {}).get("agency_ref"),
        )
        response = client.call(system=RECOMMENDATION_SYSTEM, user=user)
        calls += 1
        parsed = response.parsed
        if not parsed:
            continue
        new_severity = parsed.get("adjusted_severity")
        if (
            new_severity in SEVERITY_ORDER
            and new_severity != f.severity
            and abs(SEVERITY_ORDER.index(new_severity) - SEVERITY_ORDER.index(f.severity)) < 2
        ):
            f.severity = new_severity
            f.severity_score = score_of(new_severity)
        f.recommendation = {
            **(f.recommendation or {}),
            "layer": 3,
            "contextual": parsed.get("recommendation"),
            "action_type": parsed.get("action_type"),
            "reference_note": parsed.get("reference_note"),
        }
    return result
