"""사회 인식 반영 레이어 (레이어 2 — 법리 탐지와 분리).

회의록 docs/MEETING_social_perception_2026-06-10.md §4 합의:
사회 현저성 지수(SSI)는 탐지 F1 에 영향 0, 정비 우선순위·리포트 맥락 전용.
"""
from .salience import (
    SocialSalience,
    compute_ssi,
    extract_topic_terms,
    score_valence,
)

__all__ = ["SocialSalience", "compute_ssi", "extract_topic_terms", "score_valence"]
