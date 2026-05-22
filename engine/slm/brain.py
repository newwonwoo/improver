"""뇌신경망 SLM 핵심 — 카테고리별 분석기 (CategoryBrain).

각 카테고리(구조/공정성/적법성/거버넌스/효율성)마다 별도 신경망 모듈이
R2 구조 신호의 가중 결합으로 진단을 산출.

설계:
1. 입력 레이어: FeatureVector (~30 dims)
2. 카테고리별 가중치 (verdict-fitted)
3. 활성화: severity threshold + confidence

가중치는 verdict 데이터 기반 캘리브레이션(R3) 으로 도출.
초기 가중치는 도메인 지식 + 룰 엔진 정탐 패턴 분석 기반.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schema import Article, Law
from ..structure import ArticleDecomposition, decompose
from .features import FeatureVector, extract_features


# 카테고리 라벨
CATEGORIES = ("구조", "공정성", "적법성", "거버넌스", "효율성")


@dataclass
class CategoryDiagnosis:
    """단일 카테고리 진단 결과."""
    category: str
    article_number: str
    article_title: str
    score: float                              # [0, 1] 결함 가능성
    severity: str | None = None               # 심각/경고/주의/개선/None
    confidence: float = 0.0                   # [0, 1] 진단 확신도
    contributing_signals: list[tuple[str, float]] = field(default_factory=list)
    # (signal_name, contribution) — 결정에 기여한 신호 상위 N개

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "article_number": self.article_number,
            "article_title": self.article_title,
            "score": round(self.score, 3),
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "contributing_signals": [
                {"signal": s, "weight": round(w, 3)}
                for s, w in self.contributing_signals[:5]
            ],
        }


# === 카테고리별 가중치 ===
# 각 가중치는 R2 신호명 → 점수 contribution.
# 양수: 결함 가능성 증가, 음수: 정상 입법 신호 (감쇄).
# 초기값은 도메인 지식 + 룰 엔진 분석 기반.

WEIGHTS: dict[str, dict[str, float]] = {
    "구조": {
        # S-04 (열거 과다) 위주: items_max·catchall 가 핵심
        "items_max": 0.35,
        "catchall_strict": 0.20,
        "catchall_loose": 0.15,
        "n_paragraphs": 0.10,
        # 단순 정의·벌칙·목적은 감쇄
        "is_definition": -0.30,
        "is_purpose": -0.40,
        "is_penalty": -0.20,
        # 처분제목 시 결함성 부스트
        "disp_strong": 0.15,
        "has_grant": 0.05,
    },
    "공정성": {
        # F-01~05 통합 신호
        "disp_strong": 0.30,        # 강 처분
        "disp_mid": 0.15,
        "has_deemed_assent": 0.25,  # F-04 의제
        "has_short_deadline": 0.20,
        "has_very_short_deadline": 0.30,
        "is_prohibition": 0.10,
        "is_disposition": 0.15,
        "is_penalty": -0.20,
        "is_purpose": -0.40,
        # 청문·기준 명시 시 감쇄
        "has_hearing": -0.20,
        "has_standard": -0.10,
        # 면책 패턴은 별도 (F-02) — 약한 양수
        "subj_operator": 0.10,
        # Phase 5 감사패턴 신호 — F-07·F-08 직결
        "has_subjective_criteria": 0.30,  # F-08 자의적 기준
    },
    "적법성": {
        # L-01~03 통합 신호 — 인용 다수가 핵심
        "cited_laws_count": 0.40,
        "cited_articles": 0.25,
        "internal_refs": 0.10,
        # 인허가의제·관계특례 컨텍스트
        "has_delegate": 0.05,
        # Phase 4 그래프 — 다른 조문이 본 조문을 인용 (cross-article 위임/근거 hub)
        "graph_indegree_norm": 0.20,
        "graph_outdegree_norm": 0.15,
        "graph_centrality_norm": 0.15,
        # Phase 5 감사패턴 신호 — L-04·L-06 직결
        "has_blanket_delegation": 0.30,  # L-04 포괄위임
        "has_no_deadline_binding": 0.20, # L-06 기속처분 기한 부재
        # 단순 정의·벌칙은 감쇄
        "is_definition": -0.25,
        "is_penalty": -0.30,
        "is_purpose": -0.40,
    },
    "거버넌스": {
        # G-01~05 통합
        "proviso_max": 0.20,        # G-01 단서 과다
        "proviso_total": 0.20,
        "disp_strong": 0.15,
        "has_grant": 0.10,          # G-02 인허가
        "has_revoke": 0.10,
        "has_impose": 0.10,
        "has_report": 0.10,         # G-05 보고
        "subj_agency": 0.10,
        # Phase 4 그래프 — 위원회·기관 허브 조문 indicator
        "graph_centrality_norm": 0.10,
        # 정의·목적·벌칙은 감쇄
        "is_definition": -0.30,
        "is_purpose": -0.40,
        "is_penalty": -0.20,
        # 청문 명시 시 감쇄
        "has_hearing": -0.10,
    },
    "효율성": {
        # E-01 (조건 중첩) 주력 + 호 과다
        "items_max": 0.25,
        "catchall_strict": 0.15,
        "internal_refs": 0.20,      # 다단 절차의 핵심 — internal_refs 다수
        "n_paragraphs": 0.15,
        "body_length": 0.10,
        "is_procedure": 0.10,
        "is_delegation": 0.05,
        # Phase 4 — outdegree 가 높을수록 절차 분기 多
        "graph_outdegree_norm": 0.15,
        "is_definition": -0.30,
        "is_purpose": -0.40,
        "is_penalty": -0.20,
        # 조건 복잡도 신호 — E-01 의 핵심
        "condition_lead_norm": 0.20,
        "condition_link_norm": 0.15,
        "nested_hint_norm": 0.25,
    },
}


# Severity 임계값 — score 구간 매핑
# 캘리브레이션 가중치 사용시 누적 score 가 커지므로 임계값 상향
def _classify_severity(score: float) -> str | None:
    """[0,1] score → 심각/경고/주의/개선/None."""
    if score >= 0.90:
        return "심각"
    if score >= 0.75:
        return "경고"
    if score >= 0.60:
        return "주의"
    if score >= 0.45:
        return "개선"
    return None


@dataclass
class CategoryBrain:
    """단일 카테고리의 신경망 모듈.

    Forward pass: FeatureVector → score → severity.
    가중치는 R3 (verdict-fitted) 캘리브레이션으로 갱신 가능.
    """
    category: str
    weights: dict[str, float] = field(default_factory=dict)
    bias: float = 0.0

    @classmethod
    def for_category(cls, category: str, *, calibrated: bool = True) -> "CategoryBrain":
        """카테고리별 신경망 모듈.

        calibrated=True (기본): outputs/slm_weights_calibrated.json 우선 로드.
        파일 부재시 도메인 지식 기반 WEIGHTS 활용.
        """
        if category not in WEIGHTS:
            raise ValueError(f"unknown category: {category}")
        if calibrated:
            calib_path = Path("outputs/slm_weights_calibrated.json")
            if calib_path.exists():
                try:
                    calibrated_weights = json.loads(calib_path.read_text(encoding="utf-8"))
                    if category in calibrated_weights:
                        # 도메인 가중치 + 캘리브레이션 가중치 평균 (양쪽 모두 있을 때)
                        merged = dict(WEIGHTS[category])
                        for sig, w in calibrated_weights[category].items():
                            if sig in merged:
                                merged[sig] = (merged[sig] + w) / 2  # 평균
                            else:
                                merged[sig] = w * 0.5  # 캘리브레이션 단독 — 보수적
                        # 정상 입법 baseline — 모든 카테고리 동일 bias
                        return cls(category=category, weights=merged, bias=-0.10)
                except (json.JSONDecodeError, OSError):
                    pass
        return cls(category=category, weights=dict(WEIGHTS[category]))

    def forward(self, fv: FeatureVector) -> CategoryDiagnosis:
        """카테고리 진단 산출.

        score = sigmoid(Σ w_i · x_i + bias) 와 유사하지만,
        해석 가능성을 위해 단순 [0,1] clip + 기여도 추적.
        """
        feature_dict = fv.to_dict()
        contributions: list[tuple[str, float]] = []
        raw_score = self.bias
        for sig, w in self.weights.items():
            x = feature_dict.get(sig, 0.0)
            c = w * x
            raw_score += c
            if abs(c) > 1e-3:
                contributions.append((sig, c))

        # [0, 1] clip (실제 신경망은 sigmoid)
        score = max(0.0, min(1.0, raw_score))

        # 신뢰도 = 기여 신호의 절대 합 (정규화)
        confidence = min(1.0, sum(abs(c) for _, c in contributions))

        # 기여도 절댓값 내림차순
        contributions.sort(key=lambda t: -abs(t[1]))

        return CategoryDiagnosis(
            category=self.category,
            article_number=fv.article_number,
            article_title=fv.article_title,
            score=score,
            severity=_classify_severity(score),
            confidence=confidence,
            contributing_signals=contributions,
        )


def analyze_article(
    art: Article,
    decomp: ArticleDecomposition | None = None,
    *,
    law: Law | None = None,
    backend: str = "auto",
) -> dict[str, CategoryDiagnosis]:
    """단일 조문 → 5개 카테고리 진단.

    backend="auto": torch 모델이 있으면 torch, 없으면 linear.
    backend="linear": 항상 linear CategoryBrain 사용.
    backend="torch": 항상 torch (없으면 RuntimeError).
    law 제공시 Phase 4 그래프 신호 활용 (없으면 0).
    """
    if backend in ("auto", "torch"):
        try:
            from .torch_brain import torch_infer_article
            result = torch_infer_article(art, law=law)
            if result is not None:
                return result
        except Exception:
            pass
        if backend == "torch":
            raise RuntimeError("torch backend requested but model unavailable")

    if decomp is None:
        decomp = decompose(art)
    fv = extract_features(art, decomp, law=law)
    out: dict[str, CategoryDiagnosis] = {}
    for cat in CATEGORIES:
        brain = CategoryBrain.for_category(cat)
        out[cat] = brain.forward(fv)
    return out


def analyze_law(law: Law) -> dict[str, list[CategoryDiagnosis]]:
    """법령 단위 분석 — 각 카테고리별로 결함 조문들의 진단 리스트."""
    results: dict[str, list[CategoryDiagnosis]] = {cat: [] for cat in CATEGORIES}
    for art in law.articles:
        if art.is_definition() or art.is_purpose():
            # 분석은 하지만 출력에서는 제외
            continue
        diagnoses = analyze_article(art, law=law)
        for cat, diag in diagnoses.items():
            if diag.severity is not None:
                results[cat].append(diag)
    return results
