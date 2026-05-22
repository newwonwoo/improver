"""SLM 출력 표준 schema — prompts.chat Code Review Assistant 영감.

JSON Schema 형식으로 진단 결과를 표준화. 외부 LLM API 호환.

설계:
- 단일 조문 진단: ArticleDiagnosisOut
- 법령 전체 진단: LawDiagnosisOut (collection)
- JSON serializable
- 외부 LLM 의 structured output 으로도 통용
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal


# JSON Schema 정의 — 외부 LLM API 호출시 활용
ARTICLE_DIAGNOSIS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ArticleDiagnosis",
    "type": "object",
    "required": ["article_number", "category", "severity", "score"],
    "properties": {
        "article_number": {"type": "string", "description": "조문 번호 (제N조)"},
        "article_title": {"type": "string"},
        "category": {
            "type": "string",
            "enum": ["구조", "공정성", "적법성", "거버넌스", "효율성"],
        },
        "severity": {
            "type": ["string", "null"],
            "enum": ["심각", "경고", "주의", "개선", None],
        },
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "contributing_signals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["signal", "weight"],
                "properties": {
                    "signal": {"type": "string"},
                    "weight": {"type": "number"},
                },
            },
        },
        "missing_signals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "결함을 약화시킨 신호 (정상 입법 신호)",
        },
        "suggestion": {
            "type": "string",
            "description": "권고사항 (LLM 생성 가능)",
        },
        "readability": {
            "type": "object",
            "properties": {
                "avg_words_per_sentence": {"type": "number"},
                "hanja_ratio": {"type": "number"},
                "readability_score": {"type": "number"},
            },
        },
    },
}


LAW_DIAGNOSIS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "LawDiagnosis",
    "type": "object",
    "required": ["law_name", "n_articles", "categories"],
    "properties": {
        "law_name": {"type": "string"},
        "n_articles": {"type": "integer"},
        "categories": {
            "type": "object",
            "patternProperties": {
                "^(구조|공정성|적법성|거버넌스|효율성)$": {
                    "type": "object",
                    "properties": {
                        "total_findings": {"type": "integer"},
                        "severity_distribution": {
                            "type": "object",
                            "properties": {
                                "심각": {"type": "integer"},
                                "경고": {"type": "integer"},
                                "주의": {"type": "integer"},
                                "개선": {"type": "integer"},
                            },
                        },
                        "diagnoses": {
                            "type": "array",
                            "items": {"$ref": "#/definitions/ArticleDiagnosis"},
                        },
                    },
                },
            },
        },
        "summary": {"type": "string", "description": "LLM 생성 요약"},
    },
}


# 데이터클래스 형태 (Python 운영용)
@dataclass
class SignalContribution:
    signal: str
    weight: float


@dataclass
class ReadabilityMetrics:
    avg_words_per_sentence: float
    hanja_ratio: float
    parenthetical_density: float
    readability_score: float


@dataclass
class SufficiencyOut:
    """다차원 confidence — Phase 5+ Sufficiency check."""
    feature_coverage: float = 0.0
    prediction_margin: float = 0.0
    graph_support: float = 0.0
    signal_balance: float = 0.0
    overall: float = 0.0


@dataclass
class ArticleDiagnosisOut:
    """단일 조문 카테고리 진단 — JSON 표준 출력."""
    article_number: str
    category: str
    severity: str | None
    score: float
    article_title: str = ""
    confidence: float = 0.0
    contributing_signals: list[SignalContribution] = field(default_factory=list)
    missing_signals: list[str] = field(default_factory=list)
    suggestion: str = ""
    readability: ReadabilityMetrics | None = None
    source: Literal["rule", "slm", "both", "learned"] = "slm"
    # Phase 5+: Rerank normalize + Sufficiency
    normalized_score: float = 0.0       # 카테고리 간 비교 가능 [0,1]
    sufficiency: SufficiencyOut | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["contributing_signals"] = [
            {"signal": s["signal"], "weight": round(s["weight"], 3)}
            for s in d["contributing_signals"]
        ]
        d["score"] = round(d["score"], 3)
        d["confidence"] = round(d["confidence"], 3)
        d["normalized_score"] = round(d["normalized_score"], 3)
        if d["readability"]:
            d["readability"] = {
                k: round(v, 3) for k, v in d["readability"].items()
            }
        if d["sufficiency"]:
            d["sufficiency"] = {k: round(v, 3) for k, v in d["sufficiency"].items()}
        return d


@dataclass
class CategorySummary:
    """카테고리 단위 요약 (LawDiagnosisOut 의 자식)."""
    total_findings: int
    severity_distribution: dict[str, int]
    diagnoses: list[ArticleDiagnosisOut] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_findings": self.total_findings,
            "severity_distribution": self.severity_distribution,
            "diagnoses": [d.to_dict() for d in self.diagnoses],
        }


@dataclass
class LawDiagnosisOut:
    """법령 단위 진단 — JSON 표준 출력."""
    law_name: str
    n_articles: int
    categories: dict[str, CategorySummary] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "law_name": self.law_name,
            "n_articles": self.n_articles,
            "categories": {
                cat: cs.to_dict() for cat, cs in self.categories.items()
            },
            "summary": self.summary,
        }


def diagnosis_to_standard(diag, source: str = "slm",
                          readability_dict: dict | None = None,
                          ranked=None) -> ArticleDiagnosisOut:
    """CategoryDiagnosis (engine/slm/brain.py) → ArticleDiagnosisOut.

    내부 dataclass 를 외부 JSON schema 형식으로 변환.
    ranked (RankedDiagnosis) 제공시 normalized_score + sufficiency 채움.
    """
    sigs = [
        SignalContribution(signal=name, weight=w)
        for name, w in diag.contributing_signals[:10]
    ]
    # 음수 가중치 신호 = 결함을 약화시킨 신호 (missing_signals)
    missing = [name for name, w in diag.contributing_signals if w < 0][:5]

    readability = None
    if readability_dict:
        readability = ReadabilityMetrics(
            avg_words_per_sentence=readability_dict.get("avg_words_per_sentence", 0.0),
            hanja_ratio=readability_dict.get("hanja_ratio", 0.0),
            parenthetical_density=readability_dict.get("parenthetical_density", 0.0),
            readability_score=readability_dict.get("readability_score", 0.0),
        )

    normalized = 0.0
    sufficiency = None
    severity = diag.severity
    if ranked is not None:
        normalized = ranked.normalized_score
        sufficiency = SufficiencyOut(
            feature_coverage=ranked.sufficiency.feature_coverage,
            prediction_margin=ranked.sufficiency.prediction_margin,
            graph_support=ranked.sufficiency.graph_support,
            signal_balance=ranked.sufficiency.signal_balance,
            overall=ranked.sufficiency.overall,
        )
        severity = ranked.severity

    return ArticleDiagnosisOut(
        article_number=diag.article_number,
        article_title=diag.article_title,
        category=diag.category,
        severity=severity,
        score=diag.score,
        confidence=diag.confidence,
        contributing_signals=sigs,
        missing_signals=missing,
        readability=readability,
        source=source,  # type: ignore
        normalized_score=normalized,
        sufficiency=sufficiency,
    )
