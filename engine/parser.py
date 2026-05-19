"""조문 파서 (엔진 설계서 §2.3).

raw-legal 모드 — 「」 마스킹으로 본문 내 타법 인용을 분리.
조 → 항(원문자) → 호(아라비아숫자) → 목(가나다) 4계층 분리.
"""
from __future__ import annotations

import re

from .schema import Article, Item, Law, Paragraph

_CHAPTER_PAT = re.compile(r"^제\d+장\s+.+$", re.MULTILINE)
_ARTICLE_HEAD_PAT = re.compile(
    r"^제(?P<num>\d+)조(?P<insert>(?:의\d+)*)\s*(?:[\(（](?P<title>[^)）]+)[\)）])?",
    re.MULTILINE,
)
_PARA_HEAD_PAT = re.compile(r"^(?P<num>[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])", re.MULTILINE)
_ITEM_HEAD_PAT = re.compile(r"^\s+(?P<num>\d+)\\?\.\s+", re.MULTILINE)
_SUBITEM_HEAD_PAT = re.compile(r"^\s+(?P<num>[가-힣])\\?\.\s+", re.MULTILINE)
_DATE_PAT = re.compile(r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.")
_ADDENDUM_PAT = re.compile(r"^부\s*칙", re.MULTILINE)


def _mask_law_citations(text: str) -> tuple[str, list[str]]:
    """「...」 안의 텍스트를 마스킹해 본문 내 "제N조" 등이 조문 분리를 깨지 않도록."""
    saved: list[str] = []

    def repl(m: re.Match[str]) -> str:
        saved.append(m.group(0))
        return f"CITE{len(saved) - 1}"

    masked = re.sub(r"「[^」]+」", repl, text)
    return masked, saved


def _unmask(text: str, saved: list[str]) -> str:
    def repl(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        return saved[idx]

    return re.sub(r"CITE(\d+)", repl, text)


def _strip_addendum(text: str) -> str:
    m = _ADDENDUM_PAT.search(text)
    return text[: m.start()] if m else text


def _calc_insert_depth(insert_suffix: str) -> int:
    """'의2의3' → depth 2."""
    if not insert_suffix:
        return 0
    return insert_suffix.count("의")


def _parse_items(para_text: str) -> list[Item]:
    """항 텍스트에서 호 분리. 날짜 패턴(2025. 1. 1.)은 제외."""
    cleaned = _DATE_PAT.sub("", para_text)
    matches = list(_ITEM_HEAD_PAT.finditer(cleaned))
    items: list[Item] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        body = cleaned[start:end].strip()
        items.append(Item(item_id=f"i{i + 1}", number=m.group("num") + ".", text=body))
    return items


def _parse_paragraphs(article_text: str, article_id: str) -> list[Paragraph]:
    """원문자(①②③) 기반 항 분리. 없으면 전체를 ①항으로."""
    matches = list(_PARA_HEAD_PAT.finditer(article_text))
    if not matches:
        return [Paragraph(para_id=f"{article_id}_p1", number=None, text=article_text.strip(),
                          items=_parse_items(article_text))]
    paragraphs: list[Paragraph] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(article_text)
        body = article_text[start:end].strip()
        paragraphs.append(
            Paragraph(
                para_id=f"{article_id}_p{i + 1}",
                number=m.group("num"),
                text=body,
                items=_parse_items(body),
            )
        )
    return paragraphs


def _attach_chapter(text: str, article_pos: int) -> str | None:
    """주어진 조문 위치 직전의 가장 가까운 '제N장 ...' 찾기."""
    chapter = None
    for m in _CHAPTER_PAT.finditer(text):
        if m.start() < article_pos:
            chapter = m.group(0).strip()
        else:
            break
    return chapter


def _strip_markdown_headers(text: str) -> str:
    """마크다운 헤더(#+ )에서 # 기호 제거 — 법령.md 형식 지원.

    '##### 제1조 (목적)' → '제1조 (목적)'
    '## 제2장 총칙' → 그대로 (장/편 헤더는 _CHAPTER_PAT이 처리)
    """
    return re.sub(r"^#{1,6}\s+(제\d)", r"\1", text, flags=re.MULTILINE)


def parse_law(raw_text: str, *, name: str, law_id: str | None = None,
              law_type: str = "법률", **meta: str) -> Law:
    """텍스트 → Law 객체."""
    body = _strip_addendum(raw_text)
    # 마크다운 형식(법령.md) 지원 — '##### 제N조' 헤더 정규화
    body = _strip_markdown_headers(body)
    masked, saved = _mask_law_citations(body)

    article_matches = list(_ARTICLE_HEAD_PAT.finditer(masked))
    articles: list[Article] = []
    for i, m in enumerate(article_matches):
        start = m.start()
        end = article_matches[i + 1].start() if i + 1 < len(article_matches) else len(masked)
        article_text_masked = masked[start:end]
        article_text = _unmask(article_text_masked, saved).strip()

        num_raw = m.group("num")
        insert_suffix = m.group("insert") or ""
        depth = _calc_insert_depth(insert_suffix)
        full_num = f"제{num_raw}조{insert_suffix}"
        article_id = f"art_{num_raw}{insert_suffix.replace('의', '_')}"
        title = m.group("title")

        # 본문은 헤더 라인 다음부터
        header_end = article_text.find("\n")
        body_text = article_text[header_end + 1:].strip() if header_end > -1 else ""
        chapter = _attach_chapter(masked, start)

        article = Article(
            article_id=article_id,
            number=full_num,
            number_raw=num_raw,
            is_inserted=depth > 0,
            insert_depth=depth,
            title=title,
            full_text=article_text,
            paragraphs=_parse_paragraphs(body_text, article_id),
            chapter=chapter,
        )
        articles.append(article)

    return Law(
        law_id=law_id or f"act_{name}",
        name=name,
        type=law_type,
        articles=articles,
        **{k: v for k, v in meta.items() if k in {"short_name", "law_category",
                                                    "enacted_date", "last_amended_date",
                                                    "effective_date"}},
    )
