"""외부 법령 데이터 어댑터.

legalize-kr 등 표준 형식이 다른 텍스트를 우리 파서가 인식할 수 있는
plain text로 정규화한다.
"""
from .legalize_md import strip_frontmatter, normalize_legalize_md

__all__ = ["normalize_legalize_md", "strip_frontmatter"]
