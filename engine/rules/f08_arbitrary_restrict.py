"""F-08 자의적 이용제한·해지기준 (FTC-04 기반).

공정거래위원회 약관규제법 §11: 상당한 이유 없는 계약 해제·해지·해약 금지.
객관적 기준 없이 "판단하는 경우" / "인정하는 경우" 등 주관적 기준으로
이용을 제한하거나 계약을 해지하는 조항.

TP 신호:
  - "판단하는 경우" / "인정하는 경우" + "이용 제한" / "계약 해지" / "자격 취소"
  - 객관적 요건 없는 행위 제한·해지·취소 권한 부여
  - "이유 없이" / "구체적 이유 명시 없이" 이용 중지 가능

FP 필터:
  - 구체적 기준이 앞 항에 열거된 경우 ("다음 각 호의 사유에 해당하는 경우")
  - 청문·사전 통지·이의신청 절차가 명시된 경우
  - 행정기관의 기속재량 처분 (F-03 영역)
  - 정의·목적·벌칙 조문
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, Subject, is_blacklisted
from .base import PatternResult, make_finding

# 자의적 판단 기준 패턴
_SUBJECTIVE = re.compile(
    r"(?:사업자|회사|운영자|제공자|이용자|관리자)가?\s*"
    r"(?:필요하다고|적절하다고|상당하다고|부적합하다고|부당하다고|위반한다고|위반하였다고)?\s*"
    r"(?:인정|판단|결정)\s*(?:하는\s*경우|될\s*때|하면|되면)"
)
# 이용제한·해지 결과 패턴
_RESTRICT = re.compile(
    r"(이용을?\s*제한|계약을?\s*해지|서비스를?\s*(?:중단|정지|취소)"
    r"|회원\s*자격을?\s*박탈|자격을?\s*취소|탈퇴\s*처리|강제\s*탈퇴"
    r"|접속을?\s*차단|이용\s*정지)"
)
# 구체적 사유 열거 — FP (다음 각 호의 어느 하나)
_ENUMERATED = re.compile(
    r"(다음\s*각\s*호의?\s*어느\s*하나|제\d+항\s*각\s*호에?\s*해당|다음\s*각\s*호에?\s*해당)"
)
# 적법 절차 명시 — FP
_DUE_PROCESS = re.compile(
    r"(청문을?\s*(?:거쳐|실시)|사전\s*통지|이의\s*신청|소명\s*기회|고지\s*후"
    r"|\d+일\s*전에?\s*통지|서면으로\s*통보)"
)
# 행정기관 처분 — FP (행정법상 재량처분 = F-03 영역)
_ADMIN_CONTEXT = re.compile(
    r"(행정청|행정기관|처분청|인허가|영업\s*(?:정지|취소)|등록\s*취소|지정\s*취소)"
)


def _is_fp_article(art: Article) -> bool:
    if art.is_definition() or art.is_purpose() or art.is_penalty():
        return True
    return False


class F08ArbitraryRestrict:
    pattern_id = "F-08"
    pattern_name = "자의적이용제한기준"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        if is_blacklisted(law.name, "F-08"):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            d = decompose(art)
            text = art.full_text

            has_subjective = bool(_SUBJECTIVE.search(text))
            has_restrict = bool(_RESTRICT.search(text))

            # 이용제한/해지가 없으면 발화 안 함
            if not has_restrict:
                continue
            # 주관적 기준이 없으면 FP 가능성 높음 (skip)
            if not has_subjective:
                # 단순 "이용 제한" 패턴만 있으면 개선 수준
                # 충분한 컨텍스트 없으면 무시
                continue

            # 구체적 사유 열거 — FP
            if _ENUMERATED.search(text):
                continue
            # 적법 절차 명시 — FP
            if _DUE_PROCESS.search(text):
                continue
            # 행정기관 처분 맥락 — FP
            if _ADMIN_CONTEXT.search(text) and d.primary_subject == Subject.AGENCY:
                continue

            m_subj = _SUBJECTIVE.search(text)
            m_rest = _RESTRICT.search(text)

            # 행정기관이 아닌 사업자 주체 + 구체적 기준 없음
            if d.primary_subject in (Subject.OPERATOR, Subject.EVERYONE):
                severity = "경고"
            else:
                severity = "주의"

            idx += 1
            findings.append(make_finding(
                self, idx,
                PatternResult(
                    article=art,
                    severity=severity,
                    matched_text=f"{m_subj.group(0)} → {m_rest.group(0)}",
                    summary="주관적 기준에 의한 이용 제한·해지: 객관적 사유 열거 및 적법 절차 명시 필요",
                    fix_type="replace",
                    sub_check_id="F-08-a",
                ),
            ))
        return findings
