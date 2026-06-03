"""F-09 설명의무·계약서 교부의무 부재 (FSS-01·FSS-05 기반).

금융소비자보호법 §19(설명의무)·§23(계약서류 제공): 금융상품 판매 시
주요 내용 설명 및 계약서 교부 의무.
금융거래·금융상품·보험계약 조항에서 설명의무/고지의무/계약서교부 조항 누락.

TP 신호:
  - 금융상품·보험·대출·투자 계약 조항 + "설명하여야" / "고지하여야" 없음
  - 계약서·약관 교부 없이 계약 체결 가능한 구조
  - "계약을 체결" / "상품에 가입" + 설명·교부 의무 누락

FP 필터:
  - 이미 "설명하여야", "고지하여야", "교부하여야" 등이 명시된 경우
  - 기관 간 계약 (소비자 보호 불필요)
  - 정의·목적·벌칙 조문
  - 설명의무 규정이 별도 조문으로 존재 (해당 법의 다른 조에서 커버)
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, Subject, is_blacklisted
from .base import PatternResult, make_finding

# 금융상품·서비스 컨텍스트
_FINANCIAL = re.compile(
    r"(금융\s*상품|금융\s*서비스|금융\s*거래|대출|보험\s*(?:계약|상품|가입)"
    r"|투자\s*상품|펀드|신탁|예금|적금|파생\s*상품|증권|채권|주식|연금)"
)
# 계약 체결 / 상품 가입 패턴
_CONTRACT = re.compile(
    r"(계약을?\s*(?:체결|맺|성립)|상품에?\s*(?:가입|가입을?)|서비스를?\s*(?:신청|이용))"
)
# 설명·교부 의무 명시 — FP
_DISCLOSURE = re.compile(
    r"(설명하여야|고지하여야|교부하여야|제공하여야|안내하여야"
    r"|설명\s*의무|고지\s*의무|교부\s*의무|서면으로\s*제공"
    r"|계약서를?\s*교부|약관을?\s*교부|설명서를?\s*제공)"
)
# 기관 간 거래 — FP (소비자 보호 불필요)
_INTERAGENCY = re.compile(
    r"(금융\s*기관\s*간|기관투자자|전문투자자|기관\s*간\s*약정)"
)


def _is_fp_article(art: Article) -> bool:
    if art.is_definition() or art.is_purpose() or art.is_penalty():
        return True
    return False


def _law_has_disclosure(law: Law) -> bool:
    """법령 내 다른 조문에서 설명의무 이미 규정했는지 체크."""
    for art in law.articles:
        if _DISCLOSURE.search(art.full_text):
            return True
    return False


class F09Disclosure:
    pattern_id = "F-09"
    pattern_name = "설명의무·계약서교부의무부재"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        if is_blacklisted(law.name, "F-09"):
            return []
        # 법 전체에 설명의무 규정이 없는 경우만 대상
        # (다른 조문에서 커버하면 FP)
        law_has_disclosure = _law_has_disclosure(law)
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            d = decompose(art)
            text = art.full_text

            has_financial = bool(_FINANCIAL.search(text))
            has_contract = bool(_CONTRACT.search(text))

            # 금융 컨텍스트 + 계약 체결 둘 다 있어야 TP 가능
            if not has_financial or not has_contract:
                continue

            # 이미 설명의무가 명시된 경우 — FP
            if _DISCLOSURE.search(text):
                continue
            # 기관 간 거래 — FP
            if _INTERAGENCY.search(text):
                continue
            # 법 전체에서 커버되면 경감
            if law_has_disclosure:
                severity = "개선"
            else:
                severity = "주의"

            # 소비자 대상 주체 확인 (operator/citizen 위주)
            if d.primary_subject == Subject.AGENCY:
                # 행정기관이 금융상품을 판매하는 경우는 드물지만 체크
                severity = "개선"

            m = _CONTRACT.search(text)
            idx += 1
            findings.append(make_finding(
                self, idx,
                PatternResult(
                    article=art,
                    severity=severity,
                    matched_text=m.group(0),
                    summary="금융상품·계약 조항에서 설명의무·계약서 교부의무 미명시"
                    + (" (타 조문 설명의무 존재)" if law_has_disclosure else ""),
                    fix_type="add_paragraph",
                    sub_check_id="F-09-a",
                ),
            ))
        return findings
