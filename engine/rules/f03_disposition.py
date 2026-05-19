"""F-03 처분·명령 (설계서 §3.2 F-03)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_judicial_law, is_labor_welfare_law
from .base import PatternResult, make_finding


_STRONG = re.compile(r"(영업정지|인허가\s*취소|등록\s*취소|폐쇄\s*명령|해임\s*요구|인가\s*취소|허가\s*취소|면허\s*취소|지정\s*취소|자격\s*취소)")
_MID = re.compile(r"(시정\s*명령|과징금|업무\s*정지)")
# 주의: "주의" 단독 매칭은 FP. 행정처분으로서의 경고/주의만 해당
_WEAK = re.compile(r"(시정\s*권고|개선\s*명령|경고\s*처분|구두\s*경고|서면\s*경고|공식\s*경고|경고를\s*할\s*수\s*있다|경고를\s*하여야)")
_HEARING = re.compile(
    r"(청문|의견제출|의견\s*제출|이의신청|이의\s*신청"
    r"|사전\s*통지|미리\s*알려|미리\s*통지|불복|행정심판|행정소송"
    r"|의견을?\s*들어야|의견을?\s*제출할\s*수\s*있다)"
)
# 처분 기준: 별표·기준 외에도 호 단위로 사유를 열거한 경우 기준 명시로 인정
_STANDARD = re.compile(
    r"(별표|기준|등급|다음\s*각\s*호의?\s*어느\s*하나에?\s*해당"
    r"|다음\s*각\s*호와\s*같다|위반행위|위반\s*횟수|적합하지\s*아니)"
)
# FP 필터 패턴
_CIVIL_TERMINATION = re.compile(r"(계약의? 해지|계약의? 해제|합의|당사자\s*간|당사자\s*사이)")
_BENEFICIAL_ACT = re.compile(r"(납부\s*연장|분할\s*납부|감면|지원금|보조금|허가|인가|등록|지정)\s*.{0,20}(할\s*수\s*있다|하여야\s*한다)")
_SANCTION_ONLY = re.compile(r"^(과태료|벌칙|양벌규정|형벌|처벌)")  # 조문제목
# SLM signals (signal_candidates :: F-03)
# 처분 후속·인용 조문 (처분권 부여어 없이 처분 받은 자를 가리키는 인용만)
_DISPOSITION_REFERENCE = re.compile(
    r"제\s*\d+\s*조에?\s*따라\s*.{0,30}(영업정지|등록취소|폐쇄명령|허가취소|면허취소|업무정지)를?\s*받은"
)
# 결격사유·등록제한·양도제한 류 (처분 자체 X)
_DISQUALIFICATION_TITLE = re.compile(
    r"(결격\s*사유|면허\s*금지|등록\s*제한|양도\s*제한|취업\s*제한)"
)
# 보고·자료제출·권한위임 조문
_REPORTING_TITLE = re.compile(
    r"(보고|자료\s*제출|권한의?\s*위임|실적관리)"
)
# 사인간 도급해지
_PRIVATE_TERMINATION = re.compile(
    r"(관계인|발주자|수급인).{0,40}도급계약을?\s*해지할\s*수\s*있다"
)
# 법원·타기관 신청·요청
_THIRD_PARTY_REQUEST = re.compile(
    r"(법원|법원소년부|허가관청|시\s*[ㆍ·]\s*도지사)에게\s*.{0,30}(신청|요구|요청)할\s*수\s*있다"
)


class F03Disposition:
    pattern_id = "F-03"
    pattern_name = "처분·명령"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        # 사법·절차법령 — F-03 미적용 (verdict: 0 TP / 10 FP)
        if is_judicial_law(law.name):
            return []
        # 노동·복지·사회보험 법령 — F-03 미적용 (verdict: 0 TP / 14 FP)
        if is_labor_welfare_law(law.name):
            return []
        findings: list[Finding] = []
        idx = 0

        # 법령 전체에서 청문 절차 존재 여부 (다른 조문에 있을 수 있음)
        has_hearing_in_law = any(_HEARING.search(a.full_text) for a in law.articles)

        for art in law.articles:
            # FP 필터 1: 벌칙·과태료 단독 조문
            if art.is_penalty():
                continue
            # FP 필터 2: 청문 절차를 자체 규정하는 조문 (자기참조 오탐)
            if art.is_hearing_article():
                continue
            # FP 필터 3: 결격사유·취업제한 조문
            if art.is_disqualification():
                continue
            # FP 필터 4: 목적·정의 조문
            if art.is_purpose() or art.is_definition():
                continue
            # FP 필터 5: 조문제목이 벌칙/과태료/양벌규정
            if art.title and _SANCTION_ONLY.match(art.title.strip()):
                continue
            # Structural gates (verdict 분석)
            decomp = decompose(art)
            if decomp.type == ArticleType.COMMITTEE:
                continue
            s = decomp.primary_subject.value
            if decomp.type == ArticleType.PROHIBITION and s == "UNKNOWN":
                continue
            # GENERAL+UNKNOWN with MUST/NONE/DEFINITION modal = pure FP (9 FP total)
            from ..structure import Modal
            modal_str = "NONE"
            for p in decomp.paragraphs:
                if p.modal != Modal.NONE:
                    modal_str = p.modal.value
                    break
            if decomp.type == ArticleType.GENERAL and s == "UNKNOWN" and modal_str in (
                    "MUST", "NONE", "DEFINITION"):
                continue
            if decomp.type == ArticleType.GENERAL and s == "AGENCY" and modal_str == "MUST":
                continue
            # FP 필터 6: 사인간 민사 해지·해제 조문
            text = art.full_text
            if _CIVIL_TERMINATION.search(text) and not _STRONG.search(text):
                continue
            # SLM filters (signal_candidates :: F-03)
            title = art.title or ""
            # 결격사유·등록제한 (처분 X)
            if _DISQUALIFICATION_TITLE.search(title):
                continue
            # 보고·자료제출·위임 (처분 X)
            if _REPORTING_TITLE.search(title):
                continue
            # 처분 후속 인용만 (처분권 부여 X)
            if _DISPOSITION_REFERENCE.search(text) and not re.search(
                    r"(취소한다|취소하여야|정지한다|정지하여야|명할\s*수\s*있다|취소할\s*수\s*있다)", text):
                continue
            # 사인간 도급해지
            if _PRIVATE_TERMINATION.search(text):
                continue
            # 타기관 신청·요청 (처분권자가 본 조문 주체 아님)
            if _THIRD_PARTY_REQUEST.search(text) and not _STRONG.search(text):
                continue
            if _STRONG.search(text):
                strength = "강"
            elif _MID.search(text):
                strength = "중"
            elif _WEAK.search(text):
                strength = "약"
            else:
                continue

            has_standard = bool(_STANDARD.search(text))

            if strength == "강" and not has_hearing_in_law:
                severity = "심각"
            elif strength == "강" and not has_standard:
                severity = "경고"
            elif strength == "중" and not has_hearing_in_law:
                severity = "주의"
            elif strength == "약":
                severity = "개선"
            else:
                severity = "양호"

            if severity == "양호":
                continue

            idx += 1
            details = []
            if not has_hearing_in_law:
                details.append("청문 부재")
            if not has_standard:
                details.append("기준 미규정")
            # F-03-a 처분유형, F-03-b 사전절차, F-03-c 기준표, F-03-d 비례원칙
            if not has_hearing_in_law:
                sub = "F-03-b"
            elif not has_standard:
                sub = "F-03-c"
            else:
                sub = "F-03-d"
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"{strength}한 처분",
                        summary=f"{strength}한 처분 + {', '.join(details) or '비례원칙 검토'}",
                        fix_type="add_paragraph",
                        sub_check_id=sub,
                    ),
                )
            )
        return findings
