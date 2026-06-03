"""오탐 보정 레이어 (엔진 설계서 §3.3).

PR #1에서는 FPC-02(용어정의), FPC-04(벌칙조문)만 — 각 룰 내부에서 article.is_*()로 직접 처리.
이 모듈은 사후 보정(법령 단위 필터)을 담당.
"""
from __future__ import annotations

from .schema import Finding, Law


# 절차법 키워드 — FPC-03 적용 대상
_PROCEDURAL_HINTS = ("소송", "절차", "재판", "심판", "조정", "중재")


def _is_procedural(law: Law) -> bool:
    return any(h in law.name for h in _PROCEDURAL_HINTS)


def correct(law: Law, findings: list[Finding]) -> list[Finding]:
    """절차법인 경우 일부 패턴 등급을 하향 (FPC-03)."""
    if not _is_procedural(law):
        return findings

    downgrade_targets = {"E-05"}
    out: list[Finding] = []
    for f in findings:
        if f.pattern_id in downgrade_targets:
            if f.severity == "심각":
                f.severity = "주의"
            elif f.severity == "경고":
                f.severity = "개선"
            elif f.severity == "주의":
                f.is_false_positive = True
                f.false_positive_reason = "절차법 — 절차 하자로 규율됨"
                continue
        out.append(f)
    return out
