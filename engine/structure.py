"""조문 구조화 분해기 (docs/ENGINE_PRINCIPLES.md R2).

raw text → 의미 단위로 분해.  룰은 raw `full_text` 가 아니라 이 구조에 대해 동작.

기본 단위:
    ArticleType : 정의|벌칙|위임|처분|보고|위원회|절차|일반|...
    Subject     : 행정청|사업자|시민|공무원|기관|UNKNOWN
    Modal       : MUST|MAY|PROHIBITED|DEFINITION|NONE
    ActionKind  : GRANT(부여)|REVOKE(취소·박탈)|REPORT|REGISTER|DELEGATE|RESTRICT|DEFINE|...

LLM 검증 데이터셋(2,318 verdicts)에서 추출한 패턴에 근거.  엔진의 모든 룰이
이 분해 결과를 받아 동작하면 키워드급 → SLM급으로의 단계 상승이 가능.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .schema import Article


class ArticleType(str, Enum):
    DEFINITION = "DEFINITION"     # 정의 (이 법에서 ... 말한다)
    PENALTY = "PENALTY"           # 벌칙 (N년 이하 징역/벌금/과태료)
    DELEGATION = "DELEGATION"     # 위임 (대통령령·시행령으로 정한다)
    DISPOSITION = "DISPOSITION"   # 처분 (취소·정지·과징금)
    REPORTING = "REPORTING"       # 보고·자료제출
    COMMITTEE = "COMMITTEE"       # 위원회·심의회 운영
    PROCEDURE = "PROCEDURE"       # 절차 (인허가 처리·신청)
    PROHIBITION = "PROHIBITION"   # 금지 (아니 된다)
    PURPOSE = "PURPOSE"           # 목적
    PLAN = "PLAN"                 # 계획 수립
    GENERAL = "GENERAL"           # 기타
    EMPTY = "EMPTY"               # 삭제·미시행 단문


class Subject(str, Enum):
    AGENCY = "AGENCY"             # 행정청 (장관·청장·시도지사·공단·공사·위원회)
    OPERATOR = "OPERATOR"         # 사업자·전문직·기관
    CITIZEN = "CITIZEN"           # 국민·시민·이용자·신청인
    OFFICIAL = "OFFICIAL"         # 공무원·소속 직원
    EVERYONE = "EVERYONE"         # 누구든지
    UNKNOWN = "UNKNOWN"


class Modal(str, Enum):
    MUST = "MUST"                 # 하여야 한다
    MAY = "MAY"                   # 할 수 있다
    PROHIBITED = "PROHIBITED"     # 아니 된다 / 못한다
    DEFINITION = "DEFINITION"     # 말한다 / 본다
    NONE = "NONE"


# 분류용 정규식 (LLM verdict 데이터 기반 캘리브레이션)
_DEFINITION_RX = re.compile(
    r"(이\s*법에서\s*(\"|『).{0,40}(\"|』).{0,20}(이?란|는|함은).{0,80}말한다"
    r"|이\s*법에서\s*사용하는\s*용어의?\s*뜻"
    r'|"[^"]+"\s*(이|라)?\s*(란|함은).{0,80}말한다)'
)
_PENALTY_RX = re.compile(
    r"(\d+년\s*이하의?\s*징역|\d+(천|만|억)?\s*원\s*이하의?\s*벌금|과태료에\s*처한다"
    r"|사형|무기징역)"
)
_DELEGATION_RX = re.compile(
    r"(대통령령|시행령|총리령|부령|시행규칙|고시)으?로\s*정(?:하|한|할|해|함)"
)
_DISPOSITION_RX = re.compile(
    r"(취소(한다|하여야|할\s*수\s*있다)|정지(한다|하여야|할\s*수\s*있다)"
    r"|영업정지|업무정지|등록말소|허가취소|면허취소|자격취소|지정취소"
    r"|과징금을?\s*부과|폐쇄(명령|할\s*수\s*있다))"
)
_REPORTING_RX = re.compile(
    r"(보고하여야|보고하게|자료를?\s*제출|결과를?\s*보고|현황을?\s*보고)"
)
_COMMITTEE_RX = re.compile(r"(위원회|심의회|평의원회|이사회|협의회).{0,40}(둔다|설치한다|구성한다)")
_PROCEDURE_RX = re.compile(
    r"((인가|허가|승인|등록|면허|지정)을?\s*받(아야|을\s*수\s*있다)"
    r"|신청을?\s*받은|신청서를?\s*제출|심사하여야)"
)
_PROHIBITION_RX = re.compile(r"(하여서는\s*아니\s*된다|하지\s*못한다|할\s*수\s*없다)")
_PLAN_RX = re.compile(r"(기본계획|종합계획|시행계획|진흥계획).{0,30}(수립|마련|확정)")
_PURPOSE_RX = re.compile(r"함을\s*목적으로\s*한다")

# Subject 식별 (문장 시작/항 시작 부근)
_AGENCY_SUBJECT_RX = re.compile(
    r"(장관|청장|시\s*[ㆍ·]\s*도지사|시ㆍ도지사|시도지사|시장|군수|구청장"
    r"|공사|공단|재단|위원회|위원장|원장|총장|이사장|기관장)[은는이가]"
)
_OPERATOR_SUBJECT_RX = re.compile(
    r"(사업자|판매업자|제조업자|수입업자|서비스업자|운영자|공급자"
    r"|세무사|변호사|회계사|법무사|변리사|관세사|건축사|의사|약사"
    r"|혈액원|의료기관|검정기관|시험기관|인증기관"
    r"|선박(의|소유자)|차주|임대인)[은는이가]"
)
_CITIZEN_SUBJECT_RX = re.compile(
    r"(국민|소비자|이용자|가입자|근로자|환자|세입자|임차인|신청인|청구인)[은는이가]"
)
_OFFICIAL_SUBJECT_RX = re.compile(r"(소속\s*공무원|소속\s*직원|공무원)[은는이가]")
_EVERYONE_SUBJECT_RX = re.compile(r"누구든지")

# 빈 조문 (삭제)
_EMPTY_RX = re.compile(r"삭제")


@dataclass
class ParagraphDecomposition:
    para_index: int
    text: str
    subject: Subject = Subject.UNKNOWN
    modal: Modal = Modal.NONE
    has_adversarial_action: bool = False  # 침익적 처분·금지·명령
    has_disposition: bool = False
    has_obligation: bool = False
    has_prohibition: bool = False


@dataclass
class ArticleDecomposition:
    """SLM-level 분해 결과. 룰은 이 객체에 대해 동작."""
    article: Article
    type: ArticleType = ArticleType.GENERAL
    paragraphs: list[ParagraphDecomposition] = field(default_factory=list)
    primary_subject: Subject = Subject.UNKNOWN
    # 누적 신호 (article-level)
    has_definition_signal: bool = False
    has_penalty_signal: bool = False
    has_delegation_signal: bool = False
    has_disposition_signal: bool = False
    has_reporting_signal: bool = False
    has_committee_signal: bool = False
    has_procedure_signal: bool = False
    has_prohibition_signal: bool = False
    has_plan_signal: bool = False


def _classify_subject(text: str) -> Subject:
    """단일 텍스트 chunk 에서 주체를 식별."""
    head = text[:120]  # 문장 앞부분만 — 주체는 보통 문두에 있음
    if _EVERYONE_SUBJECT_RX.search(head):
        return Subject.EVERYONE
    if _OFFICIAL_SUBJECT_RX.search(head):
        return Subject.OFFICIAL
    if _AGENCY_SUBJECT_RX.search(head):
        return Subject.AGENCY
    if _OPERATOR_SUBJECT_RX.search(head):
        return Subject.OPERATOR
    if _CITIZEN_SUBJECT_RX.search(head):
        return Subject.CITIZEN
    return Subject.UNKNOWN


def _classify_modal(text: str) -> Modal:
    if _PROHIBITION_RX.search(text):
        return Modal.PROHIBITED
    if "할 수 있다" in text or "할 수 있고" in text:
        return Modal.MAY
    if "하여야 한다" in text or "하여야 하며" in text:
        return Modal.MUST
    if "말한다" in text or "본다" in text:
        return Modal.DEFINITION
    return Modal.NONE


def _classify_article_type(art: Article) -> ArticleType:
    """주요 신호 우선순위로 article type 결정."""
    title = art.title or ""
    text = art.full_text
    body_start = text[:300]

    # 1. 삭제·빈 조문
    if len(text.strip()) < 60 and _EMPTY_RX.search(text):
        return ArticleType.EMPTY
    # 2. 정의
    if "정의" in title or "용어" in title or _DEFINITION_RX.search(body_start):
        return ArticleType.DEFINITION
    # 3. 목적
    if "목적" in title or _PURPOSE_RX.search(body_start):
        return ArticleType.PURPOSE
    # 4. 벌칙 (제목 또는 본문 강한 신호)
    if title.startswith(("벌칙", "과태료", "양벌", "처벌", "형벌")):
        return ArticleType.PENALTY
    if _PENALTY_RX.search(body_start):
        return ArticleType.PENALTY
    # 5. 위원회 운영
    if _COMMITTEE_RX.search(text) and ("위원회" in title or "심의회" in title or "이사회" in title):
        return ArticleType.COMMITTEE
    # 6. 처분 (취소·정지·과징금)
    if _DISPOSITION_RX.search(text):
        return ArticleType.DISPOSITION
    # 7. 위임 (대통령령으로 정한다)
    if _DELEGATION_RX.search(text) and not any(s in text for s in ("취소", "정지", "처분")):
        return ArticleType.DELEGATION
    # 8. 보고
    if _REPORTING_RX.search(text):
        return ArticleType.REPORTING
    # 9. 절차 (인허가 처리)
    if _PROCEDURE_RX.search(text):
        return ArticleType.PROCEDURE
    # 10. 금지
    if _PROHIBITION_RX.search(text):
        return ArticleType.PROHIBITION
    # 11. 계획 수립
    if _PLAN_RX.search(text):
        return ArticleType.PLAN
    return ArticleType.GENERAL


def decompose(art: Article) -> ArticleDecomposition:
    """Article → ArticleDecomposition (SLM-level)."""
    text = art.full_text
    art_type = _classify_article_type(art)

    para_decomps: list[ParagraphDecomposition] = []
    para_subjects: list[Subject] = []
    if art.paragraphs:
        paras = [(i, p.text) for i, p in enumerate(art.paragraphs) if p.text.strip()]
    else:
        paras = [(0, text)]
    for idx, pt in paras:
        subj = _classify_subject(pt)
        modal = _classify_modal(pt)
        para_decomps.append(ParagraphDecomposition(
            para_index=idx,
            text=pt,
            subject=subj,
            modal=modal,
            has_adversarial_action=bool(_DISPOSITION_RX.search(pt) or _PROHIBITION_RX.search(pt)),
            has_disposition=bool(_DISPOSITION_RX.search(pt)),
            has_obligation=(modal == Modal.MUST),
            has_prohibition=(modal == Modal.PROHIBITED),
        ))
        para_subjects.append(subj)

    # primary subject — 가장 자주 등장하는 비-UNKNOWN 주체
    non_unknown = [s for s in para_subjects if s != Subject.UNKNOWN]
    if non_unknown:
        from collections import Counter
        primary = Counter(non_unknown).most_common(1)[0][0]
    else:
        primary = Subject.UNKNOWN

    return ArticleDecomposition(
        article=art,
        type=art_type,
        paragraphs=para_decomps,
        primary_subject=primary,
        has_definition_signal=bool(_DEFINITION_RX.search(text)),
        has_penalty_signal=bool(_PENALTY_RX.search(text)),
        has_delegation_signal=bool(_DELEGATION_RX.search(text)),
        has_disposition_signal=bool(_DISPOSITION_RX.search(text)),
        has_reporting_signal=bool(_REPORTING_RX.search(text)),
        has_committee_signal=bool(_COMMITTEE_RX.search(text)),
        has_procedure_signal=bool(_PROCEDURE_RX.search(text)),
        has_prohibition_signal=bool(_PROHIBITION_RX.search(text)),
        has_plan_signal=bool(_PLAN_RX.search(text)),
    )
