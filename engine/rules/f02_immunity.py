"""F-02 면책 조항 (설계서 §3.2 F-02)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_PATTERN_A = re.compile(r"(책임을 지지 아니한다|책임이 없다|책임을 면한다|면책)")
_PATTERN_B = re.compile(r"(손해를 배상하지 아니한다)")
_PATTERN_C = re.compile(
    r"(일체의\s*책임|어떠한.{0,20}책임을?\s*(지지\s*아니|없|면)"
    r"|모든\s*책임을?\s*(지지\s*아니|면\s*하|없\s*다))"
)
# 고의·중과실 예외 — 넓은 패턴
_EXCEPTION = re.compile(
    r"(고의\s*(또는|이나|·|와)?\s*(중대?한\s*)?과실"
    r"|고의\s*·\s*중과실"
    r"|중과실\s*(제외|있는|이\s*있)"
    r"|악의(인\s*경우|일\s*때)"
    r"|상당한\s*주의를\s*하였음을\s*증명)"
)
# FP: 도산·파산 면책 컨텍스트 (채무탕감, 행정면책 아님)
_INSOLVENCY = re.compile(
    r"(면책결정|면책허가|면책불허가|면책신청|파산선고|파산관재인"
    r"|채무자\s*회생|회생계획인가|파산폐지|파산재단)"
)
# FP: 불가항력·천재지변 한정 면책
_FORCE_MAJEURE = re.compile(r"(천재지변|불가항력|자연재해|전시|사변)")
# FP: 국가배상법 단서 존재 → 면책이 제한됨
_STATE_COMP_SAVING = re.compile(r"「국가배상법」에\s*따른\s*책임은\s*면제되지\s*아니한다")
# FP: 각 호 한정 면책사유 열거 (사유가 명확히 제한됨)
_LIMITED_ENUM = re.compile(
    r"다음\s*각\s*호의?\s*(어느\s*하나에\s*해당하는\s*경우를\s*제외하고"
    r"|사유로\s*발생한\s*하자에\s*대하여)"
)
# FP: 민·상사 책임 배분 (행정면책 아님)
_CIVIL_LAW_CONTEXT = re.compile(
    r"(어음법|수표법|상법상\s*책임|민법상\s*책임|담보책임|하자담보|추심위임)"
)
# FP: 적극행정 면책 (상세 기준 명시됨)
_PROACTIVE_GOV = re.compile(r"(적극\s*행정|불합리한\s*규제|낡은\s*관행).{0,50}면책")


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
    # 불가항력만 열거된 경우
    if _FORCE_MAJEURE.search(text) and not _PATTERN_C.search(text):
        return True
    return False


class F02Immunity:
    pattern_id = "F-02"
    pattern_name = "면책 조항"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty() or art.is_purpose() or art.is_definition():
                continue
            text = art.full_text
            if _is_fp_article(art, text):
                continue
            is_full = bool(_PATTERN_C.search(text))
            is_partial = bool(_PATTERN_A.search(text) or _PATTERN_B.search(text))
            if not (is_full or is_partial):
                continue
            has_exception = bool(_EXCEPTION.search(text))

            if is_full and not has_exception:
                severity = "심각"
            elif is_partial and not has_exception:
                severity = "경고"
            elif is_partial and has_exception:
                severity = "주의"
            else:
                severity = "양호"

            if severity == "양호":
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
