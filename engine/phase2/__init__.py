"""Phase 2 — 사내규정 vs 법령 비교 인프라.

설계서 §7 (적법성 판단 구조): 84 서브체크를 뒤집어 "요구사항 목록" 생성 후
사내규정과 비교해 위법유형 5종(누락/축소/초과/불일치/미갱신) 판정.

PR Round 3에서는 ① 요구사항 추출기 ② 룰 골격까지. 사내규정 텍스트 파서와
정밀 비교는 후속 작업.
"""
from .requirements import (
    Requirement,
    RequirementType,
    extract_requirements,
)
from .compare import ViolationKind, compare

__all__ = [
    "Requirement",
    "RequirementType",
    "ViolationKind",
    "compare",
    "extract_requirements",
]
