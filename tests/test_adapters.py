"""legalize-kr 어댑터 테스트."""
from engine.adapters import normalize_legalize_md, strip_frontmatter
from engine.parser import parse_law


SAMPLE = """---
제목: 테스트법
법령구분: 법률
시행일자: 2026-01-01
공포일자: 2025-12-01
---

# 테스트법

## 제1장 총칙

##### 제1조 (목적)

이 법은 테스트를 위한 법이다.

##### 제2조 (정의)

**①** 이 법에서 사용하는 용어의 뜻은 다음과 같다. <개정 2023.1.1>

  1\\. "테스트"란 시험을 말한다.
  2\\. "조문"이란 법령의 단위를 말한다.

**②** 이 법에서 정하지 아니한 사항은 다른 법에 따른다.

##### 제10조의2 (삽입조)

삽입된 조문 본문.

## 부 칙 <제2025-12-01호>

##### 제1조 (시행일)

이 법은 공포 후 6개월이 경과한 날부터 시행한다.
"""


def test_strip_frontmatter_separates_meta():
    body, meta = strip_frontmatter(SAMPLE)
    assert meta["제목"] == "테스트법"
    assert meta["시행일자"] == "2026-01-01"
    assert "법령구분" in meta
    assert "# 테스트법" in body


def test_normalize_converts_article_headers():
    body, _ = normalize_legalize_md(SAMPLE)
    assert "제1조(목적)" in body
    assert "제2조(정의)" in body
    assert "제10조의2(삽입조)" in body
    assert "##### 제1조" not in body


def test_normalize_converts_paragraph_marks():
    body, _ = normalize_legalize_md(SAMPLE)
    assert "① 이 법에서" in body
    assert "② 이 법에서" in body
    assert "**①**" not in body


def test_normalize_unescapes_item_dots():
    body, _ = normalize_legalize_md(SAMPLE)
    assert "1. " in body or "1.\t" in body
    # 백슬래시 이스케이프가 제거되어야
    assert "1\\." not in body


def test_normalized_text_parses_correctly():
    body, _ = normalize_legalize_md(SAMPLE)
    law = parse_law(body, name="테스트법")
    nums = [a.number for a in law.articles]
    # 부칙은 제외되고 본문 3개만
    assert "제1조" in nums
    assert "제2조" in nums
    assert "제10조의2" in nums
    assert len(law.articles) == 3


def test_normalized_text_extracts_items():
    body, _ = normalize_legalize_md(SAMPLE)
    law = parse_law(body, name="테스트법")
    art2 = next(a for a in law.articles if a.number == "제2조")
    para1 = art2.paragraphs[0]
    assert len(para1.items) == 2
