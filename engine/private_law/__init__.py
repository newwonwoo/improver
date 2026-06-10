"""사법(私法) 확장 — 민·상법 정비 결함 탐지 (행정규제법과 별개 체계).

팀장 결정(2026-06-10) '사법 확장 착수'의 정직한 1차 착수:
active = P-DIGITAL(날인 강제) 1종(정밀 필터 검증), scaffold = 4종(SME 큐레이션 대기).
"""
from .taxonomy import PRIVATE_LAW_TAXONOMY, active_types, scaffold_types
from .detect import detect_private_law_defects, PrivateLawFinding

__all__ = [
    "PRIVATE_LAW_TAXONOMY", "active_types", "scaffold_types",
    "detect_private_law_defects", "PrivateLawFinding",
]
