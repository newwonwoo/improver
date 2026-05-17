"""MCP 법령DB 연동 (엔진 설계서 §5).

PR #4: 로컬 인덱스 + 조회 도구 2개.
법제처 API fallback 및 폐지/제명 변경 DB는 본 모듈의 후속 단계에서 확장.
"""
from .db import (
    LawIndex,
    DecreeCoverage,
    ArticleExistence,
    check_article_exists,
    check_enforcement_decree,
    load_default_index,
)

__all__ = [
    "ArticleExistence",
    "DecreeCoverage",
    "LawIndex",
    "check_article_exists",
    "check_enforcement_decree",
    "load_default_index",
]
