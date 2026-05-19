"""S-04 열거 과다 (항 단위 호 개수).

SLM-level (docs/ENGINE_PRINCIPLES.md R2): raw text 의 호 수만 보는 게 아니라
ArticleDecomposition.type 게이트를 거쳐 발화 여부를 결정.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_judicial_law, is_blacklisted
from .base import PatternResult, make_finding

# FP 필터 패턴
_PERMIT_DEEMED = re.compile(r"(인[\s·ㆍ]?허가.{0,10}의제|다른\s*법(률|령)에\s*따른\s*인[\s·ㆍ]?허가)")
_ARTICLES_OF_ASSOC = re.compile(r"정관.{0,30}(기재|포함|사항|규정)")
_PUBLIC_INSTITUTION = re.compile(r"(사업\s*범위|사업의\s*종류|공공기관의\s*운영)")
# FP: 정관 기재사항·회원자격·수입·수수료·면제·비과세 등 표준 열거
_STD_LIST_TITLE = re.compile(
    r"(정관|회원|회비|수수료|수입|세입|세출|예산|결산|회계|급여|면제|비과세|감면"
    r"|업무|사업|시설|기준|등록\s*요건|허가\s*요건|결격\s*사유|취소\s*사유"
    r"|위반행위|준수사항|기본계획|종합계획|시행계획|시책|진흥계획"
    r"|위원회의?\s*기능|위원회의?\s*업무|심의사항|기금의?\s*용도|업무|용도"
    r"|대상사업|적용대상|적용\s*범위)"
)
# 포괄위임 종결호 — 호 자체가 아니라 마지막 호에서만 확인
_CATCHALL_ITEM = re.compile(r"그\s*밖에.{0,30}(대통령령|총리령|부령|규칙)으로\s*정하는")

# 본문 신호 — title 이 부족할 때 본문에서 분류
# Source: signal_candidates.json :: S-04
# 벌칙·과태료 본문 신호 (각호가 위반행위 구성요건 열거)
_PENALTY_BODY = re.compile(
    r"(다음\s*각\s*호의?\s*어느\s*하나에?\s*해당하는?\s*자.{0,50}"
    r"(징역|벌금|과태료|처한다|부과한다))"
    r"|(\d+년\s*이하의?\s*징역|\d+(천|만|억)?\s*원\s*이하의?\s*벌금)"
)
# 정의 조문 본문 신호 (각호가 용어 정의)
_DEFINITION_BODY = re.compile(
    r"(이\s*법에서\s*(\"|『).*(\"|』)?(이?란|의\s*뜻은|는\s*다음과\s*같다)"
    r"|이\s*법에서\s*사용하는\s*용어의?\s*뜻"
    r'|"[^"]+"\s*(이|라)?\s*(란|함은).{0,80}말한다)'
)
# 처분 사유 열거 본문 신호 (취소/정지 사유)
_DISPOSITION_GROUNDS_BODY = re.compile(
    r"다음\s*각\s*호의?\s*어느\s*하나에?\s*해당하는?\s*(경우|때)에는?"
    r".{0,80}(허가|등록|면허|지정|승인|인가)를?\s*(취소|정지)"
)
# 자료요청·기관별 권한 열거 (정보체계 인용)
_DATA_REQUEST_BODY = re.compile(
    r"(자료\s*제공\s*요청|정보\s*제공\s*요청|관계\s*기관의?\s*장에게)"
    r".{0,100}다음\s*각\s*호"
)
# 사업범위 본문 신호 (공공기관 사업 열거)
_BUSINESS_SCOPE_BODY = re.compile(
    r"(공단은?|공사는?|재단은?|진흥원은?|기금은?|위원회는?)"
    r"\s*다음\s*각\s*호의?\s*사업"
)


def _is_fp_article(art: Article) -> bool:
    """열거 과다 FP 필터 — 법제상 불가피한 호 다수 조문.

    Source: signal_candidates.json :: S-04 (LLM 검증 데이터셋 기반)
    R5 examples:
      S-04-003@선박의입항및출항등에관한법률 (FP — 제56조 벌칙 조문)
      S-04-005@하수도법 (FP — 허가취소 13호 사유)
      S-04-001@방송문화진흥회법 (FP — 정관 기재사항)
      S-04-002@전세사기피해자지원및주거안정에관한특별법 (FP — 자료요청 기관별)
    """
    # 정의·벌칙·목적 조문은 호 열거가 정상
    if art.is_definition() or art.is_penalty() or art.is_purpose():
        return True
    text = art.full_text
    title = art.title or ""
    # 인허가의제 조문 — 법적 의제 열거 불가피
    if _PERMIT_DEEMED.search(title) or _PERMIT_DEEMED.search(text[:300]):
        return True
    # 정관 기재사항 — 민법·상법 표준 형식 (제목 단독 "정관" 포함)
    if _ARTICLES_OF_ASSOC.search(title) or _ARTICLES_OF_ASSOC.search(text[:300]):
        return True
    if title.strip() == "정관":
        return True
    # 공공기관 사업범위 열거 — 설립근거법 표준
    if _PUBLIC_INSTITUTION.search(title):
        return True
    # 표준 열거 제목 (회원자격·수입·면제 등): 호 30개 미만이면 FP
    # 단, "위반행위·취소사유·결격사유" 등 침익적 열거는 보고
    if _STD_LIST_TITLE.search(title):
        adversarial_title = any(k in title for k in ("위반", "취소", "결격", "처분", "벌"))
        if not adversarial_title:
            return True
    # 본문 신호 — title 이 일반적이거나 비어있을 때만 본문 첫 200자만 보고 분류
    # (전체 본문 매칭은 진성 TP 의 호 안에서 매칭돼 오탐 위험)
    body_start = text[:200]
    # 벌칙 첫 줄 신호: "다음 각 호의 어느 하나에 해당하는 자는 ... 벌금/징역/처한다"
    if _PENALTY_BODY.search(body_start):
        return True
    # 정의 본문 신호: "이 법에서 ... 말한다"
    if _DEFINITION_BODY.search(body_start):
        return True
    return False


def _has_catchall_without_substance(para) -> bool:
    """포괄위임 종결호만 있고 구체 기준 없는 항 — TP 부스트용."""
    if not para.items:
        return False
    last_text = para.items[-1].text
    return bool(_CATCHALL_ITEM.search(last_text))


class S04Enumeration:
    pattern_id = "S-04"
    pattern_name = "열거 과다"
    category = "구조"

    def scan(self, law: Law) -> list[Finding]:
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "S-04"):
            return []
        # 사법·절차법령 — S-04 미적용 (verdict: 0 TP / 7 FP)
        if is_judicial_law(law.name):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            # Structural FP gates (verdict 분석): 순수 FP 조합
            decomp = decompose(art)
            t, s = decomp.type, decomp.primary_subject.value
            from ..structure import Modal
            modal_str = "NONE"
            for p in decomp.paragraphs:
                if p.modal != Modal.NONE: modal_str = p.modal.value; break
            if t == ArticleType.COMMITTEE:
                continue
            if t == ArticleType.REPORTING and s == "AGENCY":
                continue
            if t == ArticleType.PROHIBITION:
                continue
            if t == ArticleType.GENERAL and s in ("AGENCY", "EVERYONE"):
                continue
            if t == ArticleType.PLAN and s == "AGENCY":
                continue
            # 3-axis gates
            if t == ArticleType.DISPOSITION and s == "AGENCY" and modal_str == "MUST":
                continue
            if t == ArticleType.DISPOSITION and s == "UNKNOWN" and modal_str in ("MAY", "PROHIBITED"):
                continue
            if t == ArticleType.DELEGATION and s == "AGENCY" and modal_str == "DEFINITION":
                continue
            if t == ArticleType.DELEGATION and s == "UNKNOWN" and modal_str == "MUST":
                continue
            if t == ArticleType.PROCEDURE and s == "UNKNOWN" and modal_str == "MUST":
                continue
            if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str in ("NONE", "MAY"):
                continue
            # Aggressive (TP loss < FP cut by 4x)
            # DISPOSITION + AGENCY + MAY (4 TP / 32 FP — net 28)
            if t == ArticleType.DISPOSITION and s == "AGENCY" and modal_str == "MAY":
                continue
            # DELEGATION + AGENCY + MAY (3 TP / 9 FP — net 6)
            if t == ArticleType.DELEGATION and s == "AGENCY" and modal_str == "MAY":
                continue
            # GENERAL + UNKNOWN + MUST (1 TP / 6 FP)
            if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "MUST":
                continue
            # DELEGATION + EVERYONE + PROHIBITED (1 TP / 6 FP)
            if t == ArticleType.DELEGATION and s == "EVERYONE" and modal_str == "PROHIBITED":
                continue
            # GENERAL + UNKNOWN + DEFINITION (1 TP / 4 FP)
            if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "DEFINITION":
                continue
            # SLM signal: 호 수만으론 TP/FP 분간 불가 (TP 평균 13.4 ≈ FP 평균 13.7).
            # 컨텍스트(처분·위반·포괄위임) 신호와 결합해야 의미 있는 발화.
            art_text = art.full_text
            has_adversarial_context = bool(re.search(
                r"(취소|정지|명령|과징금|과태료|처분|위반|금지|시정명령)", art_text
            ))
            for para in art.paragraphs:
                n = len(para.items)
                # 적대적 컨텍스트 없으면 임계값 상향 (15호 이상만 발화)
                min_n = 10 if has_adversarial_context else 15
                if n < min_n:
                    continue
                if n >= 30:
                    severity = "심각"
                elif n >= 20:
                    severity = "경고"
                elif n >= 15:
                    severity = "주의"
                else:
                    severity = "개선"
                # TP 부스트: 포괄위임 종결호 + 기준 부재
                has_catchall = _has_catchall_without_substance(para)
                if has_catchall and severity in ("주의", "개선"):
                    severity = "경고"
                idx += 1
                sub = "S-04-b" if has_catchall else "S-04-a"
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=art,
                            severity=severity,
                            matched_text=f"호 {n}개" + (" + 포괄위임" if has_catchall else ""),
                            summary=f"{art.number} {para.number or ''}: 호 {n}개 나열"
                            + (" (포괄위임 종결호)" if has_catchall else ""),
                            fix_type="add_paragraph",
                            sub_check_id=sub,
                        ),
                    )
                )
        return findings
