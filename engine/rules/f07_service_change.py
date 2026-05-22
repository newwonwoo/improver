"""F-07 사업자 일방적 서비스 변경권 (FTC-02 기반).

공정거래위원회 약관규제법 §10: 고객에게 부당하게 불리한 조항은 무효.
사업자가 사전 충분한 통지 없이 서비스·요금을 일방적으로 변경할 수 있는 조항.

TP 신호:
  - "서비스/요금/이용조건을 변경할 수 있다" + 사전 통지 요건 없음
  - "필요하다고 인정하는 경우" + 서비스 변경/중단
  - 고객 동의 없는 일방적 약관 변경권

FP 필터:
  - "사전에 통지한 후", "동의를 받아", "협의하여" 등 절차 명시
  - "법령에 따라 변경이 불가피한 경우" (법령 변경 불가피)
  - 기술적 유지보수 목적 (긴급 장애 대응 등)
  - 행정기관 주체 (국민에 대한 행정처분 — F-03 영역)
  - 정의·목적·벌칙 조문
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, Subject, is_blacklisted
from .base import PatternResult, make_finding

# 서비스 변경 핵심 패턴
_CHANGE = re.compile(
    r"(서비스|이용\s*(?:요금|조건|계약)|약관|내용|방식|방법|기준|요금|수수료)\s*"
    r"(?:를|을|의)?\s*(?:변경|조정|중단|폐지|제한)\s*할\s*수\s*있다"
)
# 일방적 판단 기준 패턴 — "사업자가 필요하다고 인정/판단하는 경우"
_UNILATERAL = re.compile(
    r"(사업자|회사|이용\s*제공자|운영자)가?\s*"
    r"(?:필요하다고\s*(?:인정|판단)|적절하다고\s*(?:인정|판단)|정당한\s*사유가\s*있다고\s*인정)"
    r"\s*(?:하는\s*경우|될\s*때|되면)"
)
# 단순 변경 가능 + 이유 없음
_SIMPLE_CHANGE = re.compile(
    r"(?:이용\s*)?(?:요금|서비스|약관)(?:을|를)?\s*변경할\s*수\s*있다"
)
# 사전 통지·동의 명시 — FP
_PRIOR_NOTICE = re.compile(
    r"(사전에?\s*(?:통지|고지|안내|공지)|동의를?\s*받아|협의(?:하여|를\s*거쳐)"
    r"|\d+일\s*전에?\s*(?:통지|고지|안내)|서면으로\s*(?:통보|알림))"
)
# 법령 변경 불가피 — FP
_LEGAL_NECESSITY = re.compile(
    r"(법령(?:의|\s*에?\s*따른)\s*변경|불가피한\s*경우|천재지변|긴급한\s*(?:장애|복구))"
)
# 행정기관 주체 — FP (F-03 영역)
_ADMIN_SUBJECT = re.compile(
    r"^(행정청|행정기관|관계\s*기관|소관\s*부처|처장|청장|시장|도지사|구청장)"
)


def _is_fp_article(art: Article) -> bool:
    if art.is_definition() or art.is_purpose() or art.is_penalty():
        return True
    return False


class F07ServiceChange:
    pattern_id = "F-07"
    pattern_name = "사업자일방서비스변경권"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        if is_blacklisted(law.name, "F-07"):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            d = decompose(art)
            # 행정기관 주체면 FP (F-03 영역)
            if d.primary_subject == Subject.AGENCY:
                continue
            text = art.full_text

            has_change = bool(_CHANGE.search(text))
            has_unilateral = bool(_UNILATERAL.search(text))
            has_simple_change = bool(_SIMPLE_CHANGE.search(text))

            if not (has_change or has_unilateral or has_simple_change):
                continue

            # 사전 통지/동의 명시 — FP
            if _PRIOR_NOTICE.search(text):
                continue
            # 법령 불가피 — FP
            if _LEGAL_NECESSITY.search(text):
                continue

            if has_unilateral:
                severity = "경고"
                matched = _UNILATERAL.search(text).group(0)
                summary = "사업자 주관적 판단에 의한 일방적 서비스 변경 — 고객 동의·통지 절차 없음"
            elif has_change:
                severity = "주의"
                matched = _CHANGE.search(text).group(0)
                summary = "서비스/요금 일방 변경권: 사전 통지 요건 미명시"
            else:
                severity = "개선"
                matched = _SIMPLE_CHANGE.search(text).group(0)
                summary = "이용요금/서비스 변경 가능 규정: 사전 고지 절차 명시 권고"

            idx += 1
            findings.append(make_finding(
                self, idx,
                PatternResult(
                    article=art,
                    severity=severity,
                    matched_text=matched,
                    summary=summary,
                    fix_type="add_paragraph",
                    sub_check_id="F-07-a" if has_unilateral else "F-07-b",
                ),
            ))
        return findings
