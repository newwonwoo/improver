"""뇌신경망 SLM 입력 레이어 — R2 구조 신호를 feature vector 로 변환.

각 ArticleDecomposition 을 ~30개 정량 신호의 벡터로 표현.
신호는 카테고리별 신경망(CategoryBrain)이 가중 결합한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schema import Article
from ..structure import (
    ArticleDecomposition, ArticleType, Subject, Modal, ActionKind,
    decompose,
)


@dataclass
class FeatureVector:
    """R2 구조 신호로부터 추출된 SLM 입력 벡터.

    [0,1] 범위로 정규화된 정량 신호 + 범주형 신호 (one-hot).
    """
    # 메타데이터
    article_number: str = ""
    article_title: str = ""

    # === 범주형 신호 (one-hot 류) ===
    # ArticleType (12개)
    is_definition: float = 0.0
    is_penalty: float = 0.0
    is_delegation: float = 0.0
    is_disposition: float = 0.0
    is_reporting: float = 0.0
    is_committee: float = 0.0
    is_procedure: float = 0.0
    is_prohibition: float = 0.0
    is_purpose: float = 0.0
    is_plan: float = 0.0
    is_general: float = 0.0

    # Subject (6개)
    subj_agency: float = 0.0
    subj_operator: float = 0.0
    subj_citizen: float = 0.0
    subj_official: float = 0.0
    subj_everyone: float = 0.0

    # Modal (5개)
    modal_must: float = 0.0
    modal_may: float = 0.0
    modal_prohibited: float = 0.0
    modal_definition: float = 0.0

    # ActionKind (10개) — article-level 집합 멤버십
    has_grant: float = 0.0
    has_revoke: float = 0.0
    has_impose: float = 0.0
    has_report: float = 0.0
    has_register: float = 0.0
    has_delegate: float = 0.0
    has_restrict: float = 0.0
    has_investigate: float = 0.0
    has_hear_action: float = 0.0

    # === 정량 신호 (정규화) ===
    # 호 enumeration
    items_max: float = 0.0      # max items_count / 30 (캡)
    items_total: float = 0.0    # total items count / 50
    catchall_strict: float = 0.0  # 캐치올 STRICT 항 비율
    catchall_loose: float = 0.0   # 캐치올 LOOSE 항 비율
    # 단서
    proviso_total: float = 0.0    # total proviso / 10 (캡)
    proviso_max: float = 0.0      # max per-para / 5 (캡)
    # 인용
    cited_laws_count: float = 0.0   # /20 (캡)
    cited_articles: float = 0.0     # /30 (캡)
    internal_refs: float = 0.0      # internal_refs_unique / 20
    # 처분
    disp_strong: float = 0.0   # disposition_strength == "강"
    disp_mid: float = 0.0      # == "중"
    disp_weak: float = 0.0     # == "약"
    has_hearing: float = 0.0
    has_standard: float = 0.0
    has_deemed_assent: float = 0.0
    # 시간 기한
    has_short_deadline: float = 0.0   # min deadline < 14일
    has_very_short_deadline: float = 0.0  # min < 7일
    # 조건 복잡도 (효율성 활용)
    condition_lead_norm: float = 0.0    # condition_lead_count / 20
    condition_link_norm: float = 0.0    # condition_link_count / 30
    nested_hint_norm: float = 0.0       # nested_hint_count / 10
    # 가독성 신호 (prompts.chat Text Analyzer 영감)
    avg_words_per_sentence: float = 0.0  # [0,1] 정상화 (30 이상이면 1)
    hanja_ratio: float = 0.0             # [0,1] 정상화 (0.1 이상이면 1)
    parenthetical_density: float = 0.0   # [0,1] 정상화 (5 이상이면 1)
    readability_score: float = 0.0       # [0,1] 가독성 (1=쉬움, 0=어려움)
    # 항 수
    n_paragraphs: float = 0.0       # # paragraphs / 10
    # 텍스트 분량
    body_length: float = 0.0       # len(text) / 5000 (캡)

    def to_dict(self) -> dict[str, float]:
        return {k: v for k, v in self.__dict__.items()
                if not k.startswith("article_")}


def _norm(value: int | float, cap: float) -> float:
    """0~1 정규화 with cap."""
    if cap <= 0:
        return 0.0
    return min(float(value) / cap, 1.0)


def extract_features(art: Article, decomp: ArticleDecomposition | None = None) -> FeatureVector:
    """Article + ArticleDecomposition → FeatureVector.

    decomp 미제공시 자동 분해.
    """
    if decomp is None:
        decomp = decompose(art)

    text = art.full_text
    fv = FeatureVector(
        article_number=art.number,
        article_title=art.title or "",
    )

    # ArticleType one-hot
    type_map = {
        ArticleType.DEFINITION: "is_definition",
        ArticleType.PENALTY: "is_penalty",
        ArticleType.DELEGATION: "is_delegation",
        ArticleType.DISPOSITION: "is_disposition",
        ArticleType.REPORTING: "is_reporting",
        ArticleType.COMMITTEE: "is_committee",
        ArticleType.PROCEDURE: "is_procedure",
        ArticleType.PROHIBITION: "is_prohibition",
        ArticleType.PURPOSE: "is_purpose",
        ArticleType.PLAN: "is_plan",
        ArticleType.GENERAL: "is_general",
    }
    if decomp.type in type_map:
        setattr(fv, type_map[decomp.type], 1.0)

    # Subject one-hot (primary)
    subj_map = {
        Subject.AGENCY: "subj_agency",
        Subject.OPERATOR: "subj_operator",
        Subject.CITIZEN: "subj_citizen",
        Subject.OFFICIAL: "subj_official",
        Subject.EVERYONE: "subj_everyone",
    }
    if decomp.primary_subject in subj_map:
        setattr(fv, subj_map[decomp.primary_subject], 1.0)

    # Modal one-hot (first non-NONE)
    first_modal = Modal.NONE
    for p in decomp.paragraphs:
        if p.modal != Modal.NONE:
            first_modal = p.modal
            break
    modal_map = {
        Modal.MUST: "modal_must",
        Modal.MAY: "modal_may",
        Modal.PROHIBITED: "modal_prohibited",
        Modal.DEFINITION: "modal_definition",
    }
    if first_modal in modal_map:
        setattr(fv, modal_map[first_modal], 1.0)

    # ActionKind multi-hot
    action_map = {
        ActionKind.GRANT: "has_grant",
        ActionKind.REVOKE: "has_revoke",
        ActionKind.IMPOSE: "has_impose",
        ActionKind.REPORT: "has_report",
        ActionKind.REGISTER: "has_register",
        ActionKind.DELEGATE: "has_delegate",
        ActionKind.RESTRICT: "has_restrict",
        ActionKind.INVESTIGATE: "has_investigate",
        ActionKind.HEAR: "has_hear_action",
    }
    for ak in decomp.actions:
        if ak in action_map:
            setattr(fv, action_map[ak], 1.0)

    # 정량 신호
    items_max = max((p.items_count for p in decomp.paragraphs), default=0)
    items_total = sum(p.items_count for p in decomp.paragraphs)
    fv.items_max = _norm(items_max, 30)
    fv.items_total = _norm(items_total, 50)

    n_paras = max(len(decomp.paragraphs), 1)
    strict_count = sum(1 for p in decomp.paragraphs if p.catchall_kind == "STRICT")
    loose_count = sum(1 for p in decomp.paragraphs if p.catchall_kind == "LOOSE")
    fv.catchall_strict = strict_count / n_paras
    fv.catchall_loose = loose_count / n_paras

    fv.proviso_total = _norm(decomp.proviso_total, 10)
    fv.proviso_max = _norm(decomp.proviso_max_per_para, 5)

    fv.cited_laws_count = _norm(len(decomp.cited_laws), 20)
    fv.cited_articles = _norm(decomp.cited_articles_count, 30)
    fv.internal_refs = _norm(decomp.internal_refs_unique, 20)

    if decomp.disposition_strength == "강":
        fv.disp_strong = 1.0
    elif decomp.disposition_strength == "중":
        fv.disp_mid = 1.0
    elif decomp.disposition_strength == "약":
        fv.disp_weak = 1.0

    fv.has_hearing = 1.0 if decomp.has_hearing else 0.0
    fv.has_standard = 1.0 if decomp.has_standard else 0.0
    fv.has_deemed_assent = 1.0 if decomp.has_deemed_assent else 0.0

    if decomp.deadlines_days:
        min_dl = min(decomp.deadlines_days)
        fv.has_short_deadline = 1.0 if min_dl < 14 else 0.0
        fv.has_very_short_deadline = 1.0 if min_dl < 7 else 0.0

    fv.n_paragraphs = _norm(len(decomp.paragraphs), 10)
    fv.body_length = _norm(len(text), 5000)

    # 조건 복잡도 신호
    fv.condition_lead_norm = _norm(decomp.condition_lead_count, 20)
    fv.condition_link_norm = _norm(decomp.condition_link_count, 30)
    fv.nested_hint_norm = _norm(decomp.nested_hint_count, 10)

    # 가독성 신호 (이미 [0,1] 정상화됨)
    fv.avg_words_per_sentence = min(decomp.avg_words_per_sentence / 30.0, 1.0)
    fv.hanja_ratio = min(decomp.hanja_ratio / 0.1, 1.0)
    fv.parenthetical_density = min(decomp.parenthetical_density / 5.0, 1.0)
    fv.readability_score = decomp.readability_score

    return fv
