"""LLM 판단용 Markdown 생성기 테스트."""
from pathlib import Path

from engine import cases, cross_pattern, fpc, judgment_md, recommender, scorer
from engine.adapters import normalize_legalize_md
from engine.parser import parse_law
from engine.rules import run_all

REAL_LAW = Path(__file__).resolve().parent.parent / "data" / "laws" / "raw" / "주택도시기금법" / "법률.md"


def _run():
    text = REAL_LAW.read_text(encoding="utf-8")
    body, meta = normalize_legalize_md(text)
    law = parse_law(
        body, name="주택도시기금법", law_category="공공기관법",
        effective_date=meta.get("시행일자"),
        last_amended_date=meta.get("공포일자"),
    )
    findings = fpc.correct(law, run_all(law))
    result = scorer.compute(law, findings)
    result = recommender.apply(result)
    result = cases.attach(result)
    result = cross_pattern.annotate(result)
    return scorer.compute(law, result.findings)


def test_renders_title_and_meta():
    md = judgment_md.render(_run())
    assert "「주택도시기금법」" in md
    assert "법령 구분: 법률" in md
    assert "시행일: 2026-03-03" in md


def test_renders_llm_prompt_block():
    md = judgment_md.render(_run())
    # 새 프롬프트 구조 — 시스템 프롬프트 블록 + 작업 안내
    assert "🤖 LLM 시스템 프롬프트" in md
    assert "TP/FP/BORDER" in md
    assert "📋 이번 분석 작업" in md


def test_renders_all_articles_with_full_text():
    md = judgment_md.render(_run())
    # 43개 조문 모두 헤더로 등장해야
    assert "### 제1조" in md
    assert "### 제22조" in md
    # 본문 텍스트도 코드 블록 내에 포함
    assert "이 법은 주택도시기금을" in md


def test_renders_findings_inline():
    md = judgment_md.render(_run())
    # 등급별 요약 표
    assert "| 심각 |" in md
    # 카테고리 표
    assert "| 거버넌스 |" in md
    # 적어도 하나의 finding이 표시되어야
    assert "🔎 후보" in md


def test_renders_empty_article_marker():
    md = judgment_md.render(_run())
    # 후보가 없는 조문도 표시되어야 함
    assert "엔진 후보 없음" in md
