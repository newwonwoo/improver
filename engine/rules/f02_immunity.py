"""F-02 면책 조항 (설계서 §3.2 F-02)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_labor_welfare_law, is_blacklisted
from .base import PatternResult, make_finding


_PATTERN_A = re.compile(r"(책임을 지지 아니한다|책임이 없다|책임을 면한다|면책)")
_PATTERN_B = re.compile(r"(손해를 배상하지 아니한다)")
_PATTERN_C = re.compile(
    r"(일체의\s*책임|어떠한.{0,20}책임을?\s*(지지\s*아니|없|면)"
    r"|모든\s*책임을?\s*(지지\s*아니|면\s*하|없\s*다))"
)
# SLM signal: 전면 면책 시그니처 (signal_candidates :: F-02 :: "전면 면책 시그니처 TP 부스트")
# Rationale: "어떠한 경우에도 ... 책임 X" 같은 절대적 면책 + 고의·중과실 부재 = 명백 TP
_FULL_IMMUNITY_SIGNATURE = re.compile(
    r"(어떠한\s*경우에도|어떠한\s*의무나?\s*책임|일체의?\s*손해"
    r"|원상회복의?\s*책임을?\s*지지\s*아니|책임을?\s*부담하지\s*아니)"
)
# 고의·중과실 예외 — 넓은 패턴
# 강한 예외: "중과실" 또는 "중대한 과실" 이 명시적으로 보호됨 → 정상 입법
# Source: signal_candidates F-02 + LLM verdict 분석
# Rationale: "고의·과실"만 예외이고 "중과실"은 누락한 면책은 결함 (LLM 정답: TP)
#   → 중과실까지 보호하는 면책만 진짜 적정 한정
_STRONG_EXCEPTION = re.compile(
    r"(중과실|중대?한\s*과실"
    r"|고의\s*(또는|이나|와|·)\s*중\s*(과실|대?한\s*과실)"
    r"|고의\s*·\s*중과실"
    r"|상당한\s*주의를\s*하였음을\s*증명"
    r"|악의(인\s*경우|일\s*때))"
)
# 약한 예외: "고의·과실"만 (중과실 명시 누락)
_WEAK_EXCEPTION = re.compile(r"고의\s*(또는|이나|·|와)?\s*과실")
# 기존 호환을 위한 별칭
_EXCEPTION = _STRONG_EXCEPTION
# FP: 도산·파산 면책 컨텍스트 (채무탕감, 행정면책 아님)
_INSOLVENCY = re.compile(
    r"(면책결정|면책허가|면책불허가|면책신청|파산선고|파산관재인"
    r"|채무자\s*회생|회생계획인가|파산폐지|파산재단|회생절차|회생계획"
    r"|파산절차|파산채권|회생채권|면책취소|즉시항고)"
)
# FP: 법령명이 회생·파산·면책 관련 (전체 법률이 도산법 영역)
_INSOLVENCY_LAW = re.compile(r"(회생|파산|채무자\s*회생|면책)")
# FP: 민·상사 법령 전체 (책임 분담은 민사법의 본질, 행정 면책과 별개)
# Source: signal_candidates :: F-02 :: "민·상사 책임 배분"
# Trade-off: TP 5건 (상법 3, 민법 2) 손실 vs FP 55건 정리 (net +50)
_CIVIL_LAW_NAME = re.compile(
    r"^(상법|민법|어음법|수표법|제조물책임법|소비자기본법|신탁법"
    r"|자본시장과금융투자업에관한법률|증권관련집단소송법"
    r"|유류오염손해배상보장법|자동차손해배상보장법)$"
)
# FP: 중복 보상 조정 — 다른 법령으로 보상 받으면 그 범위 책임 면제 (사회보장 통합)
_BENEFIT_OFFSET = re.compile(
    r"(다른\s*법령에?\s*따라|「[^」]+」에?\s*따라).{0,80}"
    r"(보상을?\s*받으면|배상을?\s*받으면|급여(가|를)?\s*지급).{0,40}"
    r"(범위에서|한도에서).{0,40}(책임을?\s*지지\s*아니|책임을?\s*면|면제한다)"
)
# FP: 다른 법률에 따른 배상 등과의 조정 (제목)
_OFFSET_TITLE = re.compile(r"(다른\s*법(률|령)에?\s*따른\s*(배상|보상)|급여(와|의)\s*관계|관계\s*조정)")
# FP: 삭제·미시행 빈 조문 (본문이 거의 비어있음)
_EMPTY_ARTICLE = re.compile(r"^[\s]*제\d+조(의\d+)?[\s\(]")  # 본문 길이로 판단
# FP: 불가항력·천재지변 한정 면책
_FORCE_MAJEURE = re.compile(r"(천재지변|불가항력|자연재해|전시|사변)")
# FP: 국가배상법 단서 존재 → 면책이 제한됨
_STATE_COMP_SAVING = re.compile(
    r"「국가배상법」.{0,30}(면제되지\s*아니|책임은\s*유지|책임을\s*면\s*하지)"
)
# FP: 각 호 한정 면책사유 열거 (사유가 명확히 제한됨)
_LIMITED_ENUM = re.compile(
    r"다음\s*각\s*호의?\s*(어느\s*하나에\s*해당하는\s*경우를\s*제외하고"
    r"|사유로\s*발생한\s*하자에\s*대하여|어느\s*하나에\s*해당하면.{0,30}면책)"
)
# FP: 민·상사 책임 배분 (행정면책 아님)
_CIVIL_LAW_CONTEXT = re.compile(
    r"(어음법|수표법|상법상\s*책임|민법상\s*책임|담보책임|하자담보|추심위임"
    r"|보증채무|연대채무|채권자대위)"
)
# FP: 적극행정 면책 (상세 기준 명시됨)
_PROACTIVE_GOV = re.compile(r"(적극\s*행정|불합리한\s*규제|낡은\s*관행).{0,50}면책")
# FP: 제척기간·소멸시효·청구권 규정 (책임 자체를 면제하는 게 아님)
_TIME_LIMIT = re.compile(r"(제척기간|소멸시효|청구기간|제소기간|시효의\s*완성|시효가\s*완성)")
# FP: OSP/플랫폼 책임 제한 — 요건 명시된 제한 (면책 아닌 책임 한정)
_OSP_LIMITATION = re.compile(r"(저작권법|온라인서비스제공자|OSP|온라인\s*서비스).{0,80}(책임을?\s*제한|책임\s*없다)")
# FP: 광고시·고지·통지 의무 조문 (면책 알림 의무지 면책 자체는 아님)
_DISCLOSURE_DUTY = re.compile(r"(광고\s*시|고지하여야|통지하여야|알려야).{0,40}면책")


def _is_fp_article(art: Article, text: str) -> bool:
    if art.is_definition() or art.is_purpose():
        return True
    # 도산·파산 컨텍스트
    if _INSOLVENCY.search(text):
        return True
    # 국가배상법 단서로 이미 제한
    if _STATE_COMP_SAVING.search(text):
        return True
    # 각호 한정 면책사유 → 사유가 명확
    if _LIMITED_ENUM.search(text):
        return True
    # 민·상사 특수 컨텍스트
    if _CIVIL_LAW_CONTEXT.search(text):
        return True
    # 적극행정 면책
    if _PROACTIVE_GOV.search(text):
        return True
    # 제척기간·소멸시효 (책임 면제 아님)
    if _TIME_LIMIT.search(text):
        return True
    # OSP/플랫폼 책임 제한
    if _OSP_LIMITATION.search(text):
        return True
    # 면책 고지·통지 의무 (면책 그 자체 아님)
    if _DISCLOSURE_DUTY.search(text):
        return True
    # 불가항력만 열거된 경우
    if _FORCE_MAJEURE.search(text) and not _PATTERN_C.search(text):
        return True
    # 중복 배상 조정 (제목 또는 본문 신호)
    if _OFFSET_TITLE.search(art.title or ""):
        return True
    if _BENEFIT_OFFSET.search(text):
        return True
    # 삭제된 빈 조문 (본문 거의 비어있고 "삭제" 키워드)
    if len(text.strip()) < 150 and "삭제" in text:
        return True
    return False


class F02Immunity:
    pattern_id = "F-02"
    pattern_name = "면책 조항"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "F-02"):
            return []
        # SLM-level signal composition (docs/ENGINE_PRINCIPLES.md R1, R4)
        # Source: signal_candidates.json :: F-02
        # Rationale: "면책"이라는 단어 하나로 발화하면 안 됨.
        #   (a) 도산법 영역의 법령은 전체적으로 면책 절차를 다루는 곳이라 F-02 적용 외
        #   (b) 면책 범위가 고의·중과실 등 예외로 적정하게 한정되면 정상 입법(결함 아님)
        #   (c) 제척기간·소멸시효·OSP 책임제한은 책임 면제가 아닌 다른 제도
        # Examples (LLM verdicts justifying this):
        #   F-02-024@채무자회생및파산에관한법률 (FP — 개시신청 기각사유)
        #   F-02-001@군사법원법 (FP — 고의·중과실 예외 명시)
        #   F-02-001@공공감사에관한법률 (FP — 고의·중과실 명시 예외)
        #   F-02-001@자본시장과금융투자업에관한법률 (FP — 제척기간 1년·3년 명시)
        #   F-02-001@저작권법 (FP — OSP 책임제한 요건열거)
        # Counter-examples (TPs this filter must still catch):
        #   F-02-001@대외무역법 (TP — "어떠한 경우에도 책임X" 무제한)
        #   F-02-001@공직자윤리법 (TP — 선관주의로 일체 손해 책임 X)

        # 법령명 게이트: 도산법 영역은 전체 미적용
        if _INSOLVENCY_LAW.search(law.name):
            return []
        # 노동·복지·사회보험 법령 — F-02 미적용 (verdict: 0 TP / 6 FP)
        if is_labor_welfare_law(law.name):
            return []
        # 민·상사 법령 전체 미적용 (책임 분담은 민사법의 본질)
        # R5: F-02 verdict 분석 — 상법(TP3/FP26)·민법(TP2/FP16) net +37 noise reduction
        if _CIVIL_LAW_NAME.search(law.name):
            return []

        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty() or art.is_purpose() or art.is_definition():
                continue
            text = art.full_text
            if _is_fp_article(art, text):
                continue
            # Structural FP gates (verdict 분석)
            decomp = decompose(art)
            t, s = decomp.type, decomp.primary_subject.value
            # 위임·보고·금지 + 비-시민 주체 = 면책 조항이 아님
            if t == ArticleType.DELEGATION:
                continue  # 위임 조문에서 "면책" 매칭은 위임 사항 명시일 뿐
            if t == ArticleType.REPORTING:
                continue
            if t == ArticleType.PROHIBITION:
                continue
            # 3-axis: GENERAL + UNKNOWN + MUST (0/4)
            from ..structure import Modal
            modal_str = "NONE"
            for p in decomp.paragraphs:
                if p.modal != Modal.NONE: modal_str = p.modal.value; break
            if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "MUST":
                continue
            # GENERAL + OPERATOR + NONE modal (사업자 행위 일반 규정 —
            # 면책 본문 신호(_PATTERN_A/B/C) 없으면 FP)
            if t == ArticleType.GENERAL and s == "OPERATOR" and modal_str == "NONE":
                if not (_PATTERN_A.search(text) or _PATTERN_B.search(text) or _PATTERN_C.search(text)):
                    continue
            # Aggressive: GENERAL + UNKNOWN + NONE (1 TP / 9 FP — net 8)
            if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "NONE":
                continue
            # SLM: 전면 면책 시그니처도 is_full 로 처리 (TP 부스트)
            is_full = bool(_PATTERN_C.search(text) or _FULL_IMMUNITY_SIGNATURE.search(text))
            is_partial = bool(_PATTERN_A.search(text) or _PATTERN_B.search(text))
            if not (is_full or is_partial):
                continue
            has_strong_exc = bool(_STRONG_EXCEPTION.search(text))
            has_weak_exc = bool(_WEAK_EXCEPTION.search(text))
            # 호환: 어떤 형태든 예외 매칭
            has_exception = has_strong_exc or has_weak_exc

            # R1: "중과실"까지 명시적으로 보호되는 면책은 정상 입법 → 발화 안 함.
            # "고의·과실"만 예외인 경우는 중과실 영역이 무책임으로 빠짐 → 발화.
            if is_partial and has_strong_exc:
                continue

            if is_full and not has_strong_exc:
                severity = "심각"
            elif is_full and has_strong_exc:
                severity = "경고"  # 전면 면책이지만 중과실 보호 — 검토 대상
            elif is_partial and has_weak_exc:
                # 고의·과실만 예외 (중과실 누락) — LLM TP 패턴
                severity = "주의"
            elif is_partial and not has_exception:
                severity = "경고"
            else:
                continue

            sub = "F-02-a" if is_full else ("F-02-c" if has_exception else "F-02-b")
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text="면책",
                        summary=(
                            ("전면 면책" if is_full else "부분 면책")
                            + (" (고의·중과실 예외 없음)" if not has_exception else " (범위 불명확)")
                        ),
                        fix_type="proviso" if is_full else "replace",
                        sub_check_id=sub,
                    ),
                )
            )
        return findings
