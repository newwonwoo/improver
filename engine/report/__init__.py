"""Phase 7: 개선 진단 리포트.

LawDiagnosisOut → 사람이 읽을 수 있는 markdown / HTML.

template_report: 외부 의존성 0, 10초 이내 생성.
llm_summarize  : (옵션) ANTHROPIC_API_KEY 있을 때만 자연어 요약 추가.
"""
from .template import (
    render_markdown,
    render_json,
    build_law_diagnosis,
)

__all__ = [
    "render_markdown",
    "render_json",
    "build_law_diagnosis",
]
