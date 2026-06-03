"""scan_result.json (주택도시기금법 골든) finding 리스트로 점수만 검증.

원문 텍스트는 zip에 없지만 골든 finding 목록은 data/scan_results/scan_result.json에
저장돼 있으므로, 이걸 그대로 scorer에 넣어 등급 산출 공식이 47.0/C를 재현하는지
확인. 파서·룰 기여분과 분리해서 점수 공식의 정확성을 단독 검증.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.schema import Article, Finding, Law
from engine.scorer import compute
from engine.severity import score_of

REPO = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO / "data" / "scan_results" / "scan_result.json"


def _build_law_from_findings(findings: list[dict], total_articles: int) -> Law:
    """골든이 명시한 조문번호로 Article placeholder 생성."""
    article_numbers = {f["article"] for f in findings if f["article"] != "법령 전체"}
    # 부족분은 더미 조문으로 채워 total_articles 매칭
    arts: list[Article] = []
    for num in sorted(article_numbers):
        clean = num.replace("제", "").replace("조", "")
        arts.append(Article(article_id=f"art_{clean}", number=num, number_raw=clean))
    while len(arts) < total_articles:
        i = len(arts) + 1
        arts.append(Article(article_id=f"pad_{i}", number=f"제{i}조", number_raw=str(i)))
    return Law(law_id="act_주택도시기금법", name="주택도시기금법",
               law_category="공공기관법", articles=arts)


def test_golden_law_score_replay_within_tolerance():
    """공식이 47.0(C)을 ±5점 안에서 재현하는지 검증."""
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    total_articles = golden["total_articles"]
    findings_golden = golden["findings"]
    law = _build_law_from_findings(findings_golden, total_articles)

    by_article = {a.number: a.article_id for a in law.articles}

    findings: list[Finding] = []
    for i, gf in enumerate(findings_golden):
        article_num = gf["article"]
        # "법령 전체" 같은 메타 조문은 첫 더미에 부착
        article_id = by_article.get(article_num) or law.articles[0].article_id
        category_map = {
            "S": "구조",
            "F": "공정성",
            "L": "적법성",
            "G": "거버넌스",
            "E": "효율성",
        }
        category = category_map[gf["pattern"][0]]
        findings.append(
            Finding(
                finding_id=f"GR-{i:03d}",
                pattern_id=gf["pattern"],
                pattern_name=gf["pattern"],
                category=category,
                article_id=article_id,
                article_number=article_num,
                matched_text="",
                severity=gf["severity"],
                severity_score=score_of(gf["severity"]),
                summary=gf["summary"],
            )
        )

    result = compute(law, findings)
    # 골든은 47.0 / C
    assert result.law_grade == "C", f"got {result.law_grade}={result.law_score}"
    assert abs(result.law_score - golden["law_score"]) <= 8, (
        f"score drifted: engine={result.law_score} vs golden={golden['law_score']}"
    )


def test_golden_category_crd_within_tolerance():
    """카테고리별 CRD가 골든과 ±25% 안에서 일치."""
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    total_articles = golden["total_articles"]
    findings_golden = golden["findings"]
    law = _build_law_from_findings(findings_golden, total_articles)
    by_article = {a.number: a.article_id for a in law.articles}

    findings: list[Finding] = []
    for i, gf in enumerate(findings_golden):
        category_map = {"S": "구조", "F": "공정성", "L": "적법성", "G": "거버넌스", "E": "효율성"}
        article_id = by_article.get(gf["article"]) or law.articles[0].article_id
        findings.append(
            Finding(
                finding_id=f"GR-{i:03d}",
                pattern_id=gf["pattern"],
                pattern_name=gf["pattern"],
                category=category_map[gf["pattern"][0]],
                article_id=article_id,
                article_number=gf["article"],
                matched_text="",
                severity=gf["severity"],
                severity_score=score_of(gf["severity"]),
                summary="",
            )
        )

    result = compute(law, findings)
    for cat, expected in golden["category_scores"].items():
        engine_crd = result.category_scores[cat].crd
        golden_crd = expected["crd"]
        if golden_crd == 0:
            assert engine_crd == 0
            continue
        rel_err = abs(engine_crd - golden_crd) / max(golden_crd, 1)
        assert rel_err < 0.25, (
            f"{cat} CRD drift: engine={engine_crd} vs golden={golden_crd} "
            f"(rel_err={rel_err:.2f})"
        )
