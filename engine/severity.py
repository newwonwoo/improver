"""Severity ↔ Score 매핑 (엔진 설계서 §3.4)."""
from __future__ import annotations

SEVERITY_TO_SCORE: dict[str, int] = {
    "심각": 10,
    "경고": 7,
    "주의": 4,
    "개선": 2,
    "양호": 0,
}

SEVERITY_ORDER: list[str] = ["양호", "개선", "주의", "경고", "심각"]


def score_of(severity: str) -> int:
    return SEVERITY_TO_SCORE[severity]


def grade_of_article(score: float) -> str:
    """핵심 설계서 §1.4 Article Grade."""
    if score >= 10.0:
        return "Critical"
    if score >= 7.0:
        return "Warning"
    if score >= 4.0:
        return "Caution"
    if score > 0:
        return "Minor"
    return "Clean"


def grade_of_law(score: float) -> str:
    """핵심 설계서 §1.5 Law Grade (A~F)."""
    if score >= 75.0:
        return "F"
    if score >= 50.0:
        return "D"
    if score >= 30.0:
        return "C"
    if score >= 15.0:
        return "B"
    return "A"
