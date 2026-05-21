"""F-03 처분·명령 (설계서 §3.2 F-03)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, ActionKind, is_judicial_law, is_labor_welfare_law, is_blacklisted
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
# Method B 분석: "요청·요구·의뢰" 어미는 직접 처분 아님 (다른 기관에 요청)
# Source: Method B inline classification of F-03 FP cases
# R5 examples:
#   F-03-004@건설기술진흥법 (FP — 영업정지 요청)
#   F-03-006@건설산업기본법 (FP — 시정명령 요구)
#   F-03-002@건축법 (FP — 안전영향평가 의뢰)
_REQUEST_NOT_DISPOSITION = re.compile(
    r"(요청할\s*수\s*있다|요구할\s*수\s*있다|의뢰할\s*수\s*있다"
    r"|요청한다|요구한다|의뢰한다"
    r"|건의할\s*수\s*있다)"
)
# Method B 분석: 운전자·고용주 등의 "주의의무" 는 의무 부과지 행정처분 아님
_DUTY_OF_CARE_TITLE = re.compile(r"(주의\s*의무|안전의무|보호의무)")


class F03Disposition:
    pattern_id = "F-03"
    pattern_name = "처분·명령"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "F-03"):
            return []
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
        # SLM (signal_candidates :: F-03 :: "청문조항 동조 내 명시 → 다운그레이드"):
        # 처분조 + 동일 조문 내 청문 조항 존재 → 정상 입법 (사전절차 명시)
        def _same_art_has_hearing(art) -> bool:
            return bool(_HEARING.search(art.full_text))

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
            # Aggressive gates (TP loss < FP cut by 4x+)
            # DISPOSITION + UNKNOWN + MAY (6 TP / 25 FP — net 19) — 주체 식별 안 된 처분
            # Method B 보강: 강한 처분 본문 + 명시적 처분제목(허가/등록/면허/지정 취소…)
            # 시 게이트 통과 (verdict 3 TP / 2 FP — net +1)
            _disp_title_pre = bool(re.search(
                r"(허가\s*취소|등록\s*취소|면허\s*취소|지정\s*취소|인가\s*취소"
                r"|영업\s*정지|업무\s*정지|자격\s*취소|취소\s*등)",
                art.title or ""
            ))
            _strong_pre = bool(_STRONG.search(art.full_text))
            if (decomp.type == ArticleType.DISPOSITION and s == "UNKNOWN"
                    and modal_str == "MAY"):
                if not (_strong_pre and _disp_title_pre):
                    continue
            # DELEGATION + AGENCY + MAY (2 TP / 8 FP — net 6)
            if decomp.type == ArticleType.DELEGATION and s == "AGENCY" and modal_str == "MAY":
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
            # Method B: 주의의무·안전의무 조문은 의무부과지 처분 아님
            # Source: Method B inline classification of F-03 FP cases
            # R5 examples:
            #   F-03-002@도로교통법 (FP — 운전자 주의의무)
            #   F-03-007@도로교통법 (FP — 고용주 주의의무)
            if _DUTY_OF_CARE_TITLE.search(title):
                continue
            # Method B (Step 49): 제목 신호로 처분 강도 보완
            # 본문 _STRONG/_MID/_WEAK 미매칭이지만 제목이 "제재처분|행정처분|위반…조치|제재"
            # 인 경우 진성 처분조문 (승계·계속·후의 등 후속 조항 제외). verdict 4 TP / 0 FP
            _disposition_title_signal = bool(re.search(
                r"(제재처분|행정처분|위반.{0,10}조치|위반.{0,10}처분|^제재(\s|$))",
                title
            ))
            _post_disposition_title = bool(re.search(
                r"(승계|계속|후의|효과의?\s*승계|업무수행|상속)",
                title
            ))
            _title_only_disposition = (
                _disposition_title_signal and not _post_disposition_title
            )

            if _STRONG.search(text):
                strength = "강"
            elif _MID.search(text):
                strength = "중"
            elif _WEAK.search(text):
                strength = "약"
            elif _title_only_disposition:
                # 제목만 처분 신호 — 약한 처분으로 분류 (severity = 개선/주의)
                strength = "약"
            else:
                continue

            # R2 구조 신호 활용: ArticleDecomposition.has_standard
            has_standard = decomp.has_standard
            # SLM: 동일 조문 내 청문 명시 = 사전절차 적법 → severity 한 단계 다운
            # R2 구조 신호 활용: ArticleDecomposition.has_hearing
            same_art_hearing = decomp.has_hearing

            # Method B (Step 48, 51): 강한 처분 + 동일조 청문 부재 + DISPOSITION 타입
            # + 명시적 처분 제목 — verdict 7 TP / 0 FP (Step 48), +2 TP (Step 51 "조치")
            # 사전 절차 보장이 같은 조문에 명시되지 않은 강한 처분은 결함
            _disp_title = bool(re.search(
                r"(허가\s*취소|등록\s*취소|면허\s*취소|지정\s*취소|인가\s*취소"
                r"|설립\s*허가\s*취소|영업\s*정지|업무\s*정지|자격\s*취소"
                r"|취소\s*등|취소와\s*영업정지"
                # Step 51: "단체에 대한 조치|위반…조치명령" — 2 TP / 0 FP
                r"|에\s*대한\s*조치|위반.{0,10}조치|조치명령"
                # Step 52: 단독 "과징금" 제목 — 2 TP / 0 FP
                r"|^과징금(\s*처분)?(\s*등)?$|^과징금"
                # Step 53: 단독 "폐기" 제목 — 1 TP / 0 FP (화학무기법 §10)
                r"|^폐기$)",
                art.title or ""
            ))
            _is_disp_type = (decomp.type == ArticleType.DISPOSITION)
            _strong_disp_no_local_hearing = (
                strength == "강"
                and not same_art_hearing
                and _is_disp_type
                and _disp_title
            )

            if strength == "강" and not has_hearing_in_law:
                severity = "심각"
            elif strength == "강" and not has_standard:
                severity = "경고"
            elif strength == "중" and not has_hearing_in_law:
                severity = "주의"
            elif strength == "약":
                severity = "개선"
            elif _strong_disp_no_local_hearing and has_standard and has_hearing_in_law:
                # 강 + 처분제목 + 동일조 청문부재 = 사전 청문 cross-ref 누락 결함
                severity = "주의"
            else:
                severity = "양호"

            if severity == "양호":
                continue
            # SLM: 동일 조문 내 청문 명시 + has_standard → 정상 입법, skip
            if same_art_hearing and has_standard:
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
