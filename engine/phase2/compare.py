"""사내규정 vs 법령 요구사항 비교 (위법유형 5종 판정).

설계서 §7.2:
  ① 누락 (missing)   : require 인데 사내규정에 키워드 없음
  ② 축소 (narrowed)  : permit 인데 사내규정이 제한
  ③ 초과 (excess)    : forbid 인데 사내규정에 키워드 있음
  ④ 불일치 (mismatch): match 인데 값이 다름
  ⑤ 미갱신 (outdated): update 인데 옛 기준 사용

PR Round 3에서는 키워드 매칭 기반 단순 비교. 정밀 의미 비교는 후속 LLM 단계.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .requirements import Requirement, RequirementType


class ViolationKind(str, Enum):
    MISSING = "missing"
    NARROWED = "narrowed"
    EXCESS = "excess"
    MISMATCH = "mismatch"
    OUTDATED = "outdated"


@dataclass
class Violation:
    requirement: Requirement
    kind: ViolationKind
    detail: str

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement.to_dict(),
            "kind": self.kind.value,
            "detail": self.detail,
        }


def _has_any_keyword(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords) if keywords else True


def compare(requirements: list[Requirement], internal_text: str) -> list[Violation]:
    """사내규정 텍스트와 요구사항 목록을 비교."""
    violations: list[Violation] = []
    for req in requirements:
        present = _has_any_keyword(internal_text, req.keywords)
        if req.type == RequirementType.REQUIRE and not present:
            violations.append(Violation(
                requirement=req,
                kind=ViolationKind.MISSING,
                detail=f"법은 '{req.label}'을 요구하나 사내규정에서 미발견",
            ))
        elif req.type == RequirementType.FORBID and present:
            violations.append(Violation(
                requirement=req,
                kind=ViolationKind.EXCESS,
                detail=f"법이 금지하는 '{req.label}'이 사내규정에 포함됨",
            ))
        # NARROWED / MISMATCH / OUTDATED는 키워드 단독 매칭으로 판정 불가
        # 후속 LLM 단계에서 의미 비교 후 결정
    return violations
