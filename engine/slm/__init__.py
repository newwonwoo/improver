"""뇌신경망 SLM — R2 구조 신호를 입력으로 카테고리별 분석을 산출.

설계 (docs/ENGINE_PRINCIPLES.md SLM ladder level 4):
- Input layer  : ArticleDecomposition 의 R2 구조 신호
- Hidden layer : 카테고리별 가중 결합 (CategoryBrain)
- Output layer : 카테고리 진단 (severity + confidence + contributing_signals)

기존 룰 엔진과 병행 운영:
- 룰 → article-level finding (점 단위 결함)
- SLM → article-level 카테고리 진단 (5축 통합 진단)
"""
from .brain import CategoryBrain, analyze_article, analyze_law
from .ensemble import EnsembleVerdict, ensemble_analyze
from .features import extract_features, FeatureVector
from .output_schema import (
    ArticleDiagnosisOut, LawDiagnosisOut, CategorySummary,
    SignalContribution, ReadabilityMetrics,
    ARTICLE_DIAGNOSIS_SCHEMA, LAW_DIAGNOSIS_SCHEMA,
    diagnosis_to_standard,
)

__all__ = [
    "CategoryBrain",
    "analyze_article",
    "analyze_law",
    "extract_features",
    "FeatureVector",
    "EnsembleVerdict",
    "ensemble_analyze",
    "ArticleDiagnosisOut",
    "LawDiagnosisOut",
    "CategorySummary",
    "SignalContribution",
    "ReadabilityMetrics",
    "ARTICLE_DIAGNOSIS_SCHEMA",
    "LAW_DIAGNOSIS_SCHEMA",
    "diagnosis_to_standard",
]
