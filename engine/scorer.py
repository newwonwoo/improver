"""등급 산출 엔진 (핵심 설계서 §1.3 ~ §1.5)."""
from __future__ import annotations

from collections import defaultdict

from .schema import AnalysisResult, ArticleScore, CategoryScore, Finding, Law
from .severity import grade_of_article, grade_of_law


# 핵심 설계서 §1.5 카테고리 가중치
WEIGHTS: dict[str, dict[str, float]] = {
    "금융법": {"구조": 1.0, "공정성": 1.2, "적법성": 1.3, "거버넌스": 1.1, "효율성": 0.9},
    "공공기관법": {"구조": 1.0, "공정성": 1.0, "적법성": 1.0, "거버넌스": 1.3, "효율성": 1.2},
    "민사법": {"구조": 1.1, "공정성": 1.3, "적법성": 1.1, "거버넌스": 0.9, "효율성": 0.9},
    "절차법": {"구조": 0.9, "공정성": 1.0, "적법성": 1.0, "거버넌스": 1.1, "효율성": 1.3},
    "일반": {"구조": 1.0, "공정성": 1.0, "적법성": 1.0, "거버넌스": 1.0, "효율성": 1.0},
}

CATEGORIES = ["구조", "공정성", "적법성", "거버넌스", "효율성"]

COMPLEXITY_BONUS_PER_PATTERN = 1.5
COMPLEXITY_BONUS_CAP = 6.0
DENSITY_WEIGHT = 0.7
WORST_WEIGHT = 0.3


def _article_scores(findings: list[Finding]) -> list[ArticleScore]:
    """핵심 설계서 §1.4: Max_Severity + Complexity_Bonus(상한 6.0)."""
    by_article: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        if f.is_false_positive:
            continue
        by_article[f.article_id].append(f)

    scores: list[ArticleScore] = []
    for article_id, items in by_article.items():
        max_sev = max(f.severity_score for f in items)
        unique_patterns = {f.pattern_id for f in items}
        bonus = min((len(unique_patterns) - 1) * COMPLEXITY_BONUS_PER_PATTERN,
                     COMPLEXITY_BONUS_CAP)
        score = max_sev + bonus
        scores.append(
            ArticleScore(
                article_id=article_id,
                article_number=items[0].article_number,
                score=round(score, 2),
                grade=grade_of_article(score),
                finding_count=len(items),
            )
        )
    return scores


def _category_scores(findings: list[Finding], total_articles: int,
                     law_category: str) -> dict[str, CategoryScore]:
    """§1.5 CRD = Σ(score) / total_articles × 100."""
    weights = WEIGHTS.get(law_category, WEIGHTS["일반"])
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for f in findings:
        if f.is_false_positive:
            continue
        sums[f.category] += f.severity_score
        counts[f.category] += 1

    result: dict[str, CategoryScore] = {}
    for cat in CATEGORIES:
        crd = (sums[cat] / total_articles * 100) if total_articles else 0.0
        result[cat] = CategoryScore(
            crd=round(crd, 2),
            weight=weights[cat],
            finding_count=counts[cat],
        )
    return result


def _law_score(category_scores: dict[str, CategoryScore],
               article_scores: list[ArticleScore]) -> float:
    """§1.5 Law_Score = (Σ CRD×W / Σ W) × 0.7 + Worst × 0.3."""
    weighted_sum = sum(cs.crd * cs.weight for cs in category_scores.values())
    weight_total = sum(cs.weight for cs in category_scores.values())
    avg = (weighted_sum / weight_total) if weight_total else 0.0
    worst = max((a.score for a in article_scores), default=0.0)
    return round(avg * DENSITY_WEIGHT + worst * WORST_WEIGHT, 2)


def compute(law: Law, findings: list[Finding]) -> AnalysisResult:
    article_scores = _article_scores(findings)
    cat_scores = _category_scores(findings, law.total_articles, law.law_category)
    law_score = _law_score(cat_scores, article_scores)
    return AnalysisResult(
        law=law,
        findings=findings,
        article_scores=article_scores,
        category_scores=cat_scores,
        law_score=law_score,
        law_grade=grade_of_law(law_score),
    )
