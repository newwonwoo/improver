"""legalize-kr 형식의 법령 Markdown → 우리 파서가 인식할 plain text.

legalize-kr 포맷 특징:
- YAML frontmatter (--- ... ---)
- 조문: `##### 제N조 (제목)` (마크다운 헤더 + 공백 + 괄호)
- 항:   `**①** 본문...` (볼드 마크업으로 감싼 원문자)
- 호:   `  1\. 본문` (들여쓰기 + 이스케이프된 마침표)
- 개정 주석: `<개정 2015.8.11>` — 우리 파서는 무시해도 되지만 그대로 둠
- 부칙: `## 부칙` 마크다운 헤더
"""
from __future__ import annotations

import re

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_ARTICLE_HEADER = re.compile(r"^#{1,6}\s*제(\d+)조((?:의\d+)*)\s*(?:[\(（]([^)）]*)[\)）])?", re.MULTILINE)
_PARA_BOLD = re.compile(r"^\*\*([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\*\*\s*", re.MULTILINE)
_ITEM_ESCAPED = re.compile(r"^(\s+)(\d+)\\\.\s+", re.MULTILINE)
_SUBITEM_ESCAPED = re.compile(r"^(\s+)([가-힣])\\\.\s+", re.MULTILINE)
_CHAPTER_HEADER = re.compile(r"^#{1,6}\s*(제\d+장\s+.+)$", re.MULTILINE)
_ADDENDUM_HEADER = re.compile(r"^#{1,6}\s*부\s*칙", re.MULTILINE)
_OTHER_HEADERS = re.compile(r"^#{1,6}\s*(?!제\d+조)(?!제\d+장)(?!부\s*칙).*$", re.MULTILINE)


def strip_frontmatter(text: str) -> tuple[str, dict[str, str]]:
    """YAML frontmatter를 분리해서 (본문, 메타딕트) 반환."""
    m = _FRONTMATTER.match(text)
    if not m:
        return text, {}
    body = text[m.end():]
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip("'\"")
        if value and not value.startswith(("[", "-")):
            meta[key] = value
    return body, meta


def normalize_legalize_md(text: str) -> tuple[str, dict[str, str]]:
    """legalize-kr Markdown → 표준 plain text 변환.

    반환: (정규화된 텍스트, frontmatter 메타)
    """
    body, meta = strip_frontmatter(text)

    # 조문 헤더: "##### 제1조 (목적)" → "제1조(목적)"
    body = _ARTICLE_HEADER.sub(
        lambda m: (
            f"제{m.group(1)}조{m.group(2) or ''}"
            + (f"({m.group(3)})" if m.group(3) else "")
        ),
        body,
    )

    # 항 볼드: "**①** 본문" → "① 본문"
    body = _PARA_BOLD.sub(lambda m: f"{m.group(1)} ", body)

    # 호 이스케이프: "  1\. 본문" → "  1. 본문"
    body = _ITEM_ESCAPED.sub(lambda m: f"{m.group(1)}{m.group(2)}. ", body)
    body = _SUBITEM_ESCAPED.sub(lambda m: f"{m.group(1)}{m.group(2)}. ", body)

    # 장 헤더: "## 제2장 주택도시기금" → "제2장 주택도시기금"
    body = _CHAPTER_HEADER.sub(lambda m: m.group(1), body)

    # 부칙: "## 부칙" → "부 칙"
    body = _ADDENDUM_HEADER.sub("부 칙", body)

    # 그 외 마크다운 헤더 (예: # 주택도시기금법) → 제거
    body = _OTHER_HEADERS.sub("", body)

    return body, meta
