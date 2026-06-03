"""Stage 3: LLM 조문 분류기 (사용자 설계 그대로 구현).

조문 1개를 LLM에 던져 [A] 5축 카테고리에 대해 0~10점 결함 점수 + 이유를 JSON 으로 반환.

이 모듈은 룰 엔진과 병렬로 동작 가능 (룰 = Method A, 본 모듈 = Method B,
둘 다 같이 호출 = Method C / 하이브리드).

설계 — 사용자가 명시한 5축:
- 구조 (structure): 조문 간 충돌·참조 오류
- 공정성 (fairness): 특정 주체 과도 유리/불리
- 적법성 (legality): 상위법 위배 소지
- 거버넌스 (governance): 책임 소재·관리 주체 불명확
- 효율성 (efficiency): 불필요한 절차·중복 규제

반환 스키마:
{
  "구조": {"score": 0~10, "reason": "..."},
  "공정성": {"score": 0~10, "reason": "..."},
  "적법성": {"score": 0~10, "reason": "..."},
  "거버넌스": {"score": 0~10, "reason": "..."},
  "효율성": {"score": 0~10, "reason": "..."}
}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..schema import Article, Finding
from .client import LLMClient, make_default_client


# 5축 카테고리
AXES = ["구조", "공정성", "적법성", "거버넌스", "효율성"]


SYSTEM_PROMPT = """\
당신은 한국 법령 결함 진단 전문가다. 주어진 조문 한 개에 대해
다음 5개 축의 결함 정도를 0~10 점수로 평가하라.

평가 축:
- 구조: 조문 간 충돌이나 참조 오류, 조문 내부 정합성
- 공정성: 특정 주체에게 과도하게 유리하거나 불리한 차별, 권리 제한
- 적법성: 상위법(헌법·기본법) 위배 소지, 위임 한계 일탈
- 거버넌스: 책임 소재·관리 주체·감독 권한의 불명확성
- 효율성: 불필요한 행정 절차, 중복 규제, 아날로그 잔재

점수 기준:
- 0: 결함 없음 (해당 축에서 명확하고 정상적인 입법)
- 1-3: 경미한 결함
- 4-6: 주의가 필요한 결함
- 7-9: 명확한 결함 (개정 필요)
- 10: 심각한 결함 (당장 개정 필요)

반환은 반드시 다음 JSON 형식 (다른 설명 없이):
{
  "구조": {"score": <0-10>, "reason": "<한 문장>"},
  "공정성": {"score": <0-10>, "reason": "<한 문장>"},
  "적법성": {"score": <0-10>, "reason": "<한 문장>"},
  "거버넌스": {"score": <0-10>, "reason": "<한 문장>"},
  "효율성": {"score": <0-10>, "reason": "<한 문장>"}
}

할루시네이션 금지. 조문에 명시되지 않은 사실을 추론하지 말라.
점수가 낮으면 (0~3) 그 축의 reason은 짧게 "해당 결함 없음" 등으로 작성하라.
"""


@dataclass
class AxisScore:
    score: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "reason": self.reason}


@dataclass
class ArticleClassification:
    article_id: str
    article_number: str
    scores: dict[str, AxisScore] = field(default_factory=dict)
    raw: str = ""

    def axis_score(self, axis: str) -> int:
        return self.scores[axis].score if axis in self.scores else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "article_number": self.article_number,
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
        }


def _format_user(law_name: str, article: Article) -> str:
    return (
        f"법령명: {law_name}\n"
        f"조문: {article.number}{' ' + article.title if article.title else ''}\n\n"
        f"본문:\n{article.full_text}\n"
    )


def classify_article(
    law_name: str, article: Article, *, client: LLMClient | None = None
) -> ArticleClassification:
    """단일 조문 → 5축 결함 점수 JSON.

    Stage 3 핵심 진입점.  운영 시 LLM API 1회 호출.
    """
    client = client or make_default_client()
    response = client.call(system=SYSTEM_PROMPT, user=_format_user(law_name, article))
    parsed = response.parsed or _safe_parse(response.raw)
    classification = ArticleClassification(
        article_id=article.article_id,
        article_number=article.number,
        raw=response.raw,
    )
    if not parsed:
        return classification
    for axis in AXES:
        node = parsed.get(axis) or {}
        if isinstance(node, dict):
            score = int(node.get("score", 0))
            reason = str(node.get("reason", ""))
            classification.scores[axis] = AxisScore(
                score=max(0, min(10, score)),
                reason=reason,
            )
    return classification


def _safe_parse(text: str) -> dict[str, Any] | None:
    text = text.strip()
    # 코드블록 제거
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def classify_law(
    law_name: str, articles: list[Article], *, client: LLMClient | None = None,
    max_articles: int | None = None,
) -> list[ArticleClassification]:
    """법령 전체를 조문별 분류기에 넘김 (병렬 실행은 호출측이 결정)."""
    client = client or make_default_client()
    target = articles[:max_articles] if max_articles else articles
    return [classify_article(law_name, a, client=client) for a in target]


# Stage 4: 결정론적 가중치 — 카테고리별 가중치 적용
# (engine/scorer.py 의 WEIGHTS 와 정합)
LAW_CATEGORY_WEIGHTS: dict[str, dict[str, float]] = {
    "금융법":     {"구조": 1.0, "공정성": 1.2, "적법성": 1.3, "거버넌스": 1.1, "효율성": 0.9},
    "공공기관법": {"구조": 1.0, "공정성": 1.0, "적법성": 1.0, "거버넌스": 1.3, "효율성": 1.2},
    "민사법":     {"구조": 1.1, "공정성": 1.3, "적법성": 1.1, "거버넌스": 0.9, "효율성": 0.9},
    "절차법":     {"구조": 0.9, "공정성": 1.0, "적법성": 1.0, "거버넌스": 1.1, "효율성": 1.3},
    "일반":       {"구조": 1.0, "공정성": 1.0, "적법성": 1.0, "거버넌스": 1.0, "효율성": 1.0},
}


def aggregate_law_risk(
    classifications: list[ArticleClassification], law_category: str
) -> dict[str, Any]:
    """Stage 4: classifier 결과를 법령 단위 위험도로 통합.

    각 축의 평균 점수 × 법령 카테고리 가중치 → 가중 평균 risk_score.
    """
    weights = LAW_CATEGORY_WEIGHTS.get(law_category, LAW_CATEGORY_WEIGHTS["일반"])
    n = len(classifications) or 1
    axis_avg: dict[str, float] = {}
    for axis in AXES:
        axis_avg[axis] = sum(c.axis_score(axis) for c in classifications) / n
    weighted_sum = sum(axis_avg[a] * weights[a] for a in AXES)
    weight_total = sum(weights.values())
    risk = weighted_sum / weight_total
    return {
        "axis_avg": {a: round(axis_avg[a], 2) for a in AXES},
        "weights": weights,
        "risk_score": round(risk, 2),
        "weighted_axis": {a: round(axis_avg[a] * weights[a], 2) for a in AXES},
    }


# Stage 5: 템플릿 인젝션 — 결정론적 마크다운 리포트
LAW_REPORT_TEMPLATE = """\
# {law_name} — 결함 진단 리포트

**법령 카테고리**: {law_category}
**진단 조문 수**: {n_articles}
**가중 위험도 (Risk Score)**: {risk_score} / 10.0

## 5축 결함 분포

| 축 | 평균 점수 | 가중치 | 가중 점수 |
|---|---:|---:|---:|
{axis_table}

## 최상위 우려 조문 (Top-3 by 총점)

{top_articles}

## 개선 권고

{recommendations}
"""


def render_law_report(
    law_name: str, law_category: str,
    classifications: list[ArticleClassification],
    aggregation: dict[str, Any],
) -> str:
    """Stage 5: 결정론적 템플릿에 측정값 인젝션."""
    axes_avg = aggregation["axis_avg"]
    weights = aggregation["weights"]
    weighted = aggregation["weighted_axis"]
    axis_rows = "\n".join(
        f"| {a} | {axes_avg[a]:.2f} | {weights[a]:.1f}x | {weighted[a]:.2f} |"
        for a in AXES
    )
    # Top articles by sum of scores
    ranked = sorted(
        classifications,
        key=lambda c: sum(c.axis_score(a) for a in AXES),
        reverse=True,
    )[:3]
    if ranked:
        top_lines = []
        for c in ranked:
            total = sum(c.axis_score(a) for a in AXES)
            worst_axis = max(AXES, key=lambda a: c.axis_score(a))
            worst_score = c.axis_score(worst_axis)
            reason = c.scores.get(worst_axis, AxisScore(0, "—")).reason
            top_lines.append(
                f"- **{c.article_number}** (총점 {total}/50, 최대 결함축: {worst_axis} {worst_score}/10)\n"
                f"  - {reason}"
            )
        top_str = "\n".join(top_lines)
    else:
        top_str = "_분석된 조문 없음_"

    # Recommendations from axes with weighted score ≥ 4
    high_axes = [a for a in AXES if weighted[a] >= 4]
    if high_axes:
        rec = "\n".join(
            f"- **{a}** 축 가중 점수 {weighted[a]:.1f} — 우선 개정 검토 필요"
            for a in high_axes
        )
    else:
        rec = "_현 상태에서 즉시 개정 권고 없음 (모든 축 가중 점수 < 4.0)_"

    return LAW_REPORT_TEMPLATE.format(
        law_name=law_name,
        law_category=law_category,
        n_articles=len(classifications),
        risk_score=aggregation["risk_score"],
        axis_table=axis_rows,
        top_articles=top_str,
        recommendations=rec,
    )
