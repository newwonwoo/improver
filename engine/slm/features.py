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
    # Phase 4: GraphRAG-lite 신호 — 다른 article 과의 인용 관계
    graph_indegree_norm: float = 0.0     # 본 article 을 가리키는 다른 article 수 / 20
    graph_outdegree_norm: float = 0.0    # 본 article 이 가리키는 article 수 / 20
    graph_centrality_norm: float = 0.0   # corpus-wide degree centrality
    graph_pagerank_norm: float = 0.0     # PageRank 영향 반경 (CodeGraph impact analysis 착안)
    # 감사원·공정위·금감원 감사패턴 기반 신호 (Phase 5)
    has_blanket_delegation: float = 0.0    # 포괄위임: "필요한 사항" + 구체 기준 없이 하위법령 위임
    has_subjective_criteria: float = 0.0   # 자의적 기준: "판단하는 경우"/"인정하는 경우" + 처분
    has_no_deadline_binding: float = 0.0   # 기속처분 기한 부재: DISPOSITION + MUST + 기한 없음
    # 공정위 약관 시정·인권위 차별판단 사례 기반 신호 (Phase 6 — NaverSearch 수집 사례)
    has_refund_denial: float = 0.0         # 환불 거부/제한 (OTT·오디오북·멤버십 시정 사례)
    has_arbitrary_change: float = 0.0      # 자의적 서비스 변경·중단 ("기타 필요한 경우" 등)
    has_broad_immunity: float = 0.0        # 광범위 면책 (사업자 귀책 포함 책임 전면 배제)
    has_withdrawal_limit: float = 0.0      # 청약철회권 배제·제한 (법정 권리 제한)
    has_age_discrimination: float = 0.0    # 연령 차별 (만 N세 이하/이상 출입·이용 제한)
    # 감사원·대법원 사례 기반 법률 텍스트 신호 (Phase 6b — 법률 corpus 적용)
    has_double_sanction: float = 0.0       # 이중제재: 같은 조에 형사벌(징역·벌금) + 과태료 병과 (BAI-02)
    has_auto_max_sanction: float = 0.0     # 1:1 자동 최고제재: "위반한 자는 ...취소한다" 가중·감경 없음 (대법 JUD-01)
    has_no_hearing_disp: float = 0.0       # 침익처분 + 청문 절차 부재 (BAI-03·행정절차법 §22)
    # NaverSearch 커버리지 매트릭스로 발견한 gap 신호 (Phase 6c)
    has_no_reason_giving: float = 0.0      # 거부·취소 처분 + 이유제시 의무 부재 (대법 JUD-02·행정절차법 §23)
    # 감사원·공정위·금감원 실사례 보강 신호 (Phase 12 — 감찰기관 감사내역 반영)
    has_subdeleg_admin_rule: float = 0.0   # 고시·훈령·지침 등 행정규칙에 권리·의무 위임 (BAI-06·헌재 위임명령 한계)
    has_no_disp_standard: float = 0.0      # 재량처분 + 처분기준 사전공표 의무 부재 (BAI-08·행정절차법 §20)
    # 법제처 법령해석례 패턴 (Phase 13 — moleg 100건 분석)
    has_undefined_precedence: float = 0.0  # "다른 법률의 특별한 규정" 인용 + 우선순위 명시 부재 (법령 정합성 모호)
    # Phase 13 v2 — QA 피드백: R-DELEG-BLANKET FP 필터 (시행령 한정열거 시 발화 억제)
    has_sublaw_concrete_enum: float = 0.0  # 시행령에 해당 조문 위임사항이 한정 열거됨 (위임 구체화 완료)

    def to_dict(self) -> dict[str, float]:
        return {k: v for k, v in self.__dict__.items()
                if not k.startswith("article_")}

    def to_array(self, names: list[str] | None = None) -> list[float]:
        """지정된 feature 순서로 float list 반환 (torch 입력용)."""
        d = self.to_dict()
        if names is None:
            names = list(d.keys())
        return [float(d.get(k, 0.0)) for k in names]


# 안정적인 feature 순서 — torch 모델 학습/추론에 사용 (추가 가능, 삭제 금지)
FEATURE_NAMES: list[str] = [
    "is_definition", "is_penalty", "is_delegation", "is_disposition",
    "is_reporting", "is_committee", "is_procedure", "is_prohibition",
    "is_purpose", "is_plan", "is_general",
    "subj_agency", "subj_operator", "subj_citizen", "subj_official", "subj_everyone",
    "modal_must", "modal_may", "modal_prohibited", "modal_definition",
    "has_grant", "has_revoke", "has_impose", "has_report", "has_register",
    "has_delegate", "has_restrict", "has_investigate", "has_hear_action",
    "items_max", "items_total", "catchall_strict", "catchall_loose",
    "proviso_total", "proviso_max",
    "cited_laws_count", "cited_articles", "internal_refs",
    "disp_strong", "disp_mid", "disp_weak",
    "has_hearing", "has_standard", "has_deemed_assent",
    "has_short_deadline", "has_very_short_deadline",
    "condition_lead_norm", "condition_link_norm", "nested_hint_norm",
    "avg_words_per_sentence", "hanja_ratio", "parenthetical_density", "readability_score",
    "n_paragraphs", "body_length",
    # Phase 4 graph signals (추가)
    "graph_indegree_norm", "graph_outdegree_norm", "graph_centrality_norm",
    "graph_pagerank_norm",
    # Phase 5 감사패턴 신호 (추가 — 삭제 금지)
    "has_blanket_delegation", "has_subjective_criteria", "has_no_deadline_binding",
    # Phase 6 공정위·인권위 사례 신호 (추가 — 삭제 금지)
    "has_refund_denial", "has_arbitrary_change", "has_broad_immunity",
    "has_withdrawal_limit", "has_age_discrimination",
    # Phase 6b 감사원·대법원 법률 텍스트 신호 (추가 — 삭제 금지)
    "has_double_sanction", "has_auto_max_sanction", "has_no_hearing_disp",
    # Phase 6c NaverSearch 커버리지 gap 신호 (추가 — 삭제 금지)
    "has_no_reason_giving",
    # Phase 12 감찰기관 감사내역 보강 신호 (추가 — 삭제 금지)
    "has_subdeleg_admin_rule", "has_no_disp_standard",
    # Phase 13 법제처 법령해석례 패턴 (추가 — 삭제 금지)
    "has_undefined_precedence",
    # Phase 13 v2 QA 피드백 — R-DELEG-BLANKET FP 필터
    "has_sublaw_concrete_enum",
]


def _norm(value: int | float, cap: float) -> float:
    """0~1 정규화 with cap."""
    if cap <= 0:
        return 0.0
    return min(float(value) / cap, 1.0)


def extract_features(
    art: Article,
    decomp: ArticleDecomposition | None = None,
    *,
    law: "Article | None" = None,
) -> FeatureVector:
    """Article + ArticleDecomposition → FeatureVector.

    decomp 미제공시 자동 분해.
    law 제공시 Phase 4 그래프 신호도 채움 (없으면 0).
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

    # Phase 4 그래프 신호 — law 객체 제공시만 (per-article 호출 비용 최소화)
    if law is not None:
        try:
            from ..graph import graph_signals_for_article
            gs = graph_signals_for_article(law, art, decomp)
            fv.graph_indegree_norm = gs.indegree_norm
            fv.graph_outdegree_norm = gs.outdegree_norm
            fv.graph_centrality_norm = gs.centrality_norm
            fv.graph_pagerank_norm = gs.pagerank_norm
        except Exception:
            pass  # graph 모듈 없거나 networkx 미설치 — 0 유지

    # Phase 5 감사패턴 신호
    import re as _re
    _BLANKET_RX = _re.compile(
        r"필요한\s*사항(?:은|이|을)?\s*(?:대통령령|총리령|부령|[가-힣]+부령"
        r"|행정규칙|고시|훈령|예규|지침|내부\s*규정|업무\s*규정)으로\s*정한다"
    )
    _CONCRETE_RX = _re.compile(
        r"(제\d+항|제\d+호|각\s*호|다음\s*각\s*호|전항)에?\s*따른?\s*(기준|요건|범위|절차|조건)"
    )
    if decomp.type == ArticleType.DELEGATION and _BLANKET_RX.search(text):
        fv.has_blanket_delegation = 0.0 if _CONCRETE_RX.search(text) else 1.0

    _SUBJ_RX = _re.compile(
        r"(?:인정|판단|결정)\s*(?:하는\s*경우|될\s*때|하면)"
    )
    _RESTRICT_RX = _re.compile(
        r"(이용을?\s*제한|계약을?\s*해지|서비스를?\s*(?:중단|정지|취소)|이용\s*정지)"
    )
    if _SUBJ_RX.search(text) and _RESTRICT_RX.search(text):
        if decomp.type in (ArticleType.DISPOSITION, ArticleType.PROHIBITION, ArticleType.GENERAL):
            fv.has_subjective_criteria = 1.0

    if (
        decomp.type in (ArticleType.DISPOSITION, ArticleType.PROCEDURE)
        and any(p.modal == Modal.MUST for p in decomp.paragraphs)
        and not decomp.deadlines_days
    ):
        fv.has_no_deadline_binding = 1.0

    # Phase 6 — 공정위 약관 시정·인권위 차별판단 사례 기반 신호
    # (NaverSearch 수집 사례에서 도출한 텍스트 패턴)
    _REFUND_DENY_RX = _re.compile(
        r"(환불|환급|반환)(?:은|을|를|이|하지)?\s*(?:아니하|아니한|불가|거부|제한|하지\s*않)"
        r"|환불(?:이|을|은)?\s*되지\s*(?:아니|않)"
    )
    _PRO_CONSUMER_RX = _re.compile(
        r"(환불(?:하여야|해야|받을\s*수\s*있)|전액\s*(?:환불|환급)|청약(?:의)?\s*철회(?:를|할))"
    )
    if _REFUND_DENY_RX.search(text) and not _PRO_CONSUMER_RX.search(text):
        fv.has_refund_denial = 1.0

    # 자의적 서비스 변경·중단 — "기타 필요한 경우" 등 불명확 사유 + 변경/중단권
    _ARBITRARY_RX = _re.compile(
        r"(기타\s*(?:필요한|필요하다고\s*인정|회사가\s*정한)"
        r"|회사가?\s*(?:필요|적절)하다고\s*(?:인정|판단)"
        r"|사업자가?\s*(?:필요|임의)로)"
    )
    _CHANGE_STOP_RX = _re.compile(
        r"(변경|중단|중지|정지|폐지|종료)(?:할\s*수\s*있|하거나|하고)"
    )
    if _ARBITRARY_RX.search(text) and _CHANGE_STOP_RX.search(text):
        if decomp.type not in (ArticleType.DEFINITION, ArticleType.PURPOSE, ArticleType.PENALTY):
            fv.has_arbitrary_change = 1.0

    # 광범위 면책 — 사업자 귀책 포함 책임 전면 배제
    _IMMUNITY_RX = _re.compile(
        r"(책임을?\s*지지\s*(?:아니|않)|책임(?:이|을)?\s*(?:없|면제|부담하지\s*아니)"
        r"|어떠한?\s*(?:경우|책임)(?:에도|도).{0,20}(?:지지\s*아니|않|없|면제))"
    )
    _IMMUNITY_FP_RX = _re.compile(
        r"(천재지변|불가항력|고객의?\s*(?:고의|과실|귀책)|제3자의?\s*(?:고의|과실|귀책))"
    )
    if _IMMUNITY_RX.search(text) and not _IMMUNITY_FP_RX.search(text):
        if decomp.type not in (ArticleType.DEFINITION, ArticleType.PURPOSE, ArticleType.PENALTY):
            fv.has_broad_immunity = 1.0

    # 청약철회권 배제·제한
    _WITHDRAW_RX = _re.compile(
        r"청약(?:의)?\s*철회.{0,30}(?:불가|아니|않|제한|배제|없)"
        r"|(?:해지|해제)(?:권)?(?:을|를|는)?\s*(?:배제|제한|행사할\s*수\s*없)"
    )
    if _WITHDRAW_RX.search(text):
        if decomp.type not in (ArticleType.DEFINITION, ArticleType.PURPOSE, ArticleType.PENALTY):
            fv.has_withdrawal_limit = 1.0

    # 연령 차별 — 만 N세 이하/이상 출입·이용·가입 제한 (인권위 차별판단 사례)
    _AGE_DISCRIM_RX = _re.compile(
        r"(만\s*\d+\s*세\s*(?:이하|미만|이상|초과).{0,30}(?:제한|금지|불가|배제|거부|할\s*수\s*없)"
        r"|\d+\s*세\s*(?:이하|미만|이상|초과)(?:의|인)?\s*(?:자|사람|아동|청소년|노인).{0,30}(?:제한|금지|불가|배제))"
    )
    if _AGE_DISCRIM_RX.search(text):
        fv.has_age_discrimination = 1.0

    # Phase 6b — 감사원·대법원 사례 기반 법률 텍스트 신호 (법률 corpus 적용도 높음)
    # 이중제재 (BAI-02): 같은 조에 형사벌(징역/벌금) + 과태료 동시 규정
    _CRIMINAL_RX = _re.compile(r"(\d+년\s*이하의?\s*징역|\d+(?:천|백|십)?만?\s*원\s*이하의?\s*벌금)")
    _ADMIN_FINE_RX = _re.compile(r"과태료")
    if _CRIMINAL_RX.search(text) and _ADMIN_FINE_RX.search(text):
        fv.has_double_sanction = 1.0

    # 1:1 자동 최고제재 (대법 JUD-01): "위반한 자는 ...취소/말소한다" + 가중·감경·다만 단서 없음
    _AUTO_SANCTION_RX = _re.compile(
        r"(위반한?\s*(?:자|경우)|거짓이나?\s*그?\s*밖의?\s*부정한?\s*방법).{0,40}"
        r"(취소(?:하여야)?\s*한다|말소(?:하여야)?\s*한다|등록을?\s*취소한다)"
    )
    _MITIGATION_RX = _re.compile(r"(다만|가중|감경|경감|정상을?\s*(?:참작|고려)|2분의\s*1)")
    if _AUTO_SANCTION_RX.search(text) and not _MITIGATION_RX.search(text):
        if decomp.type in (ArticleType.DISPOSITION, ArticleType.PENALTY, ArticleType.GENERAL):
            fv.has_auto_max_sanction = 1.0

    # 침익처분 + 청문 부재 (BAI-03): 취소/정지/철회 처분 + 청문·의견청취 절차 없음
    _ADVERSE_DISP_RX = _re.compile(
        r"(허가|인가|등록|지정|승인)(?:을|를)?\s*(?:취소|철회)"
        r"|영업(?:을|의)?\s*(?:정지|폐지)|업무(?:을|를|의)?\s*정지"
    )
    _HEARING_RX = _re.compile(r"(청문|의견(?:을)?\s*(?:청취|제출|진술)|소명(?:할|의)?\s*기회)")
    if _ADVERSE_DISP_RX.search(text) and not _HEARING_RX.search(text):
        if decomp.type in (ArticleType.DISPOSITION, ArticleType.PROHIBITION):
            fv.has_no_hearing_disp = 1.0

    # Phase 6c — NaverSearch 커버리지 gap 신호
    # 이유제시 미흡 (대법 JUD-02): 거부·취소·정지 처분 + 이유제시/사유통지 의무 없음
    _DENY_DISP_RX = _re.compile(
        r"(거부|반려|취소|철회|정지|거절)(?:할\s*수\s*있|하여야|한다)"
    )
    _REASON_RX = _re.compile(
        r"(이유를?\s*(?:제시|명시|붙여|기재|적어)|사유를?\s*(?:통지|명시|기재|알려)"
        r"|그\s*사유를|이유와\s*함께)"
    )
    if _DENY_DISP_RX.search(text) and not _REASON_RX.search(text):
        if decomp.type in (ArticleType.DISPOSITION, ArticleType.PROHIBITION, ArticleType.PROCEDURE):
            fv.has_no_reason_giving = 1.0

    # Phase 12 — 감찰기관 감사내역 실사례 반영
    # BAI-06: 행정규칙(고시·훈령·지침) 위임 — 헌재 위임명령 한계 일탈
    # "...장이 정하는 바에 따른다"/"...장이 고시한다" + 위임근거 (시행령 외)
    _ADMIN_RULE_RX = _re.compile(
        r"(고시|훈령|예규|지침|규정)(?:으로|에서|에)?\s*(?:정|규정|공표)"
        r"|장관이\s*정(?:하|한)|위원회(?:가|에서)?\s*정(?:하|한)"
        r"|.\s*장이\s*정(?:하는|한다|할)"
    )
    _SUBORD_LAW_RX = _re.compile(r"(대통령령|총리령|부령|시행령|시행규칙)")
    if _ADMIN_RULE_RX.search(text) and not _SUBORD_LAW_RX.search(text):
        if decomp.type in (ArticleType.DELEGATION, ArticleType.DISPOSITION,
                           ArticleType.PROCEDURE, ArticleType.GENERAL):
            fv.has_subdeleg_admin_rule = 1.0

    # Phase 13 — 법제처 법령해석례 패턴: "다른 법률의 특별한 규정" 인용
    _PRECEDENCE_RX = _re.compile(
        r"다른\s*법(?:률|령)(?:에서)?(?:의)?\s*(?:특별한)?\s*(?:규정|정함)"
        r"|다른\s*법(?:률|령)에\s*(?:따른다|의한다)"
        r"|이\s*법(?:에서)?\s*정(?:한|하는)\s*경우(?:를)?\s*제외"
    )
    if _PRECEDENCE_RX.search(text):
        # 우선순위 명시 부재 = 어떤 법령이 특별한지 정의 안 됨
        # 본 조문 자체가 다중 법령을 인용하지 않으면 모호도 ↑
        if len(decomp.cited_laws) >= 1:
            fv.has_undefined_precedence = 1.0

    # BAI-08: 재량처분 + 처분기준 사전공표 의무 부재 (행정절차법 §20)
    # 재량 표현 + 처분 + 기준/공표/세부 사항 없음
    _DISCRETION_RX = _re.compile(
        r"(할\s*수\s*있다|인정(?:하는|되는)\s*경우|판단(?:하는|되는)\s*경우"
        r"|적당하다고\s*인정|필요하다고\s*인정)"
    )
    _STANDARD_DISCL_RX = _re.compile(
        r"(기준을?\s*(?:공표|공시|정하여\s*공표|마련하여\s*공표)"
        r"|세부\s*기준|구체적\s*기준|처분기준)"
    )
    if (_DISCRETION_RX.search(text)
        and decomp.type == ArticleType.DISPOSITION
        and not _STANDARD_DISCL_RX.search(text)):
        fv.has_no_disp_standard = 1.0

    return fv


# ─── Phase 13 v2 — 시행령·시행규칙 한정열거 enrichment (R-DELEG-BLANKET FP 필터) ───

import re as _re_mod
from pathlib import Path as _Path

_LAWS_DIR = _Path(__file__).resolve().parents[2] / "data/laws/raw"
_SUBLAW_CACHE: dict[str, str | None] = {}
_SUBLAW_CONCRETE_RX = _re_mod.compile(
    r"(?:다음\s*각\s*호|다음\s*각호)|"
    r"(?:\b1\.|\b가\.).{0,500}(?:\b3\.|\b다\.)"
)


def _read_sublaw(law_name: str) -> str | None:
    # 시행령 + 시행규칙 모두 위임 충전원. 시행령만 읽으면 시행규칙이 채운 위임
    # (예: 산안법 제130조 단서 → 시행규칙 제200조 한정열거)을 놓침.
    if law_name in _SUBLAW_CACHE:
        return _SUBLAW_CACHE[law_name]
    parts: list[str] = []
    for fname in ("시행령.md", "시행규칙.md"):
        p = _LAWS_DIR / law_name / fname
        if not p.exists():
            continue
        try:
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
    text = "\n".join(parts) if parts else None
    _SUBLAW_CACHE[law_name] = text
    return text


def enrich_with_sublaw(fv: FeatureVector, law_name: str, article_number: str) -> None:
    """시행령·시행규칙에서 해당 조문 위임사항이 한정 열거되어 있으면 신호 설정.

    R-DELEG-BLANKET FP 필터용. moleg QA 피드백 P-META-1 반영(+ 시행규칙 확장).
    """
    if not law_name or not article_number:
        return
    sublaw_text = _read_sublaw(law_name)
    if not sublaw_text:
        return
    m = _re_mod.search(r"(\d+)", article_number)
    if not m:
        return
    art_digits = m.group(1)
    # "법 제N조" 인용 위치를 모두 검색 — 첫 인용에 한정열거가 없어도
    # (예: 시행령엔 단순 인용, 시행규칙엔 한정열거) 뒤 인용에서 잡도록 순회.
    for cite_m in _re_mod.finditer(rf"법\s*제\s*{art_digits}\s*조", sublaw_text):
        chunk = sublaw_text[cite_m.start() : cite_m.start() + 1500]
        if _SUBLAW_CONCRETE_RX.search(chunk):
            fv.has_sublaw_concrete_enum = 1.0
            return
