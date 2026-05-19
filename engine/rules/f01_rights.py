"""F-01 권리 제한 + 구제수단 부재 (설계서 §3.2 F-01)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_STRONG = re.compile(
    r"(금지한다|할 수 없다|하지 못한다|박탈|자격을 상실|효력을 잃"
    r"|아니\s*된다|해서는\s*아니\s*된다|하여서는\s*아니\s*된다)"
    # 취소한다·정지한다는 F-03(처분조) 영역 — 중복 제거
)
_MID = re.compile(r"(제한한다|제한할 수 있다|배제|적용하지 아니한다|거부할 수 있다)")
_WEAK = re.compile(r"조건을 붙일 수 있다")  # "제한" 단독은 제거 (너무 광범위)
_REMEDY = re.compile(r"(이의신청|이의 신청|구제|청문|소명|행정소송|행정심판|불복)")
# TP 필터: 수범자가 일반 국민/소비자/근로자인 경우만
_CITIZEN = re.compile(r"(국민|소비자|이용자|가입자|근로자|환자|세입자|임차인|청구권자)")
# FP 필터: 처벌/제재 조문에서의 금지 (이미 E-05/F-05에서 처리)
_SANCTION_CONTEXT = re.compile(r"(징역|벌금|과태료|과징금|형사|처벌|제재)")
# FP 필터: 사업자 행위 제한 (국민 권리 침해 아님)
_OPERATOR = re.compile(
    r"(사업자|판매업자|제조업자|수입업자|서비스업자|운영자|공급자"
    r"|세무사|변호사|회계사|법무사|변리사|관세사|건축사|의사|약사"
    r"|검정기관|승인기관|시험기관|인증기관|평가기관|보증기관"
    r"|선박의?\s*소유자|선박소유자|차주"
    r"|기관의?\s*장은|기관장은)"
)
# FP 필터: 사업주/고용주가 주체 → 근로자 보호 조문 (권리 제한 아님)
_EMPLOYER_SUBJECT = re.compile(
    r"(사업주|고용주|사용자|운영자|고용인).{0,30}(하지\s*못한다|아니\s*된다|할\s*수\s*없다)"
)
# TP 필터: 실질적 권리 박탈 키워드
_DEPRIVATION = re.compile(
    r"(자격을?\s*정지|허가를?\s*취소|등록을?\s*취소|인가를?\s*취소|면허를?\s*취소"
    r"|자격을?\s*상실|직위를?\s*해제|영업을?\s*정지)"
)


class F01Rights:
    pattern_id = "F-01"
    pattern_name = "권리 제한"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        articles = law.articles
        for i, art in enumerate(articles):
            if art.is_penalty() or art.is_purpose() or art.is_definition():
                continue
            text = art.full_text
            # 단순 형사처벌 컨텍스트는 제외 (F-05 영역)
            if _SANCTION_CONTEXT.search(text):
                continue
            # 사업주/고용주가 근로자를 보호하는 조문 (근로자 권리 제한 아님)
            if _EMPLOYER_SUBJECT.search(text):
                continue
            # 주로 사업자 행위 제한 (국민 권리 침해 아님)
            if _OPERATOR.search(text) and not _CITIZEN.search(text):
                continue

            if _STRONG.search(text) or _DEPRIVATION.search(text):
                strength = "강"
            elif _MID.search(text):
                strength = "중"
            elif _WEAK.search(text):
                strength = "약"
            else:
                continue

            # 구제수단: 동일 조문 또는 ±2조 범위 (설계서 §3.2)
            window = articles[max(0, i - 2): min(len(articles), i + 3)]
            has_remedy = any(_REMEDY.search(a.full_text) for a in window)
            is_citizen = bool(_CITIZEN.search(text))

            if strength == "강" and is_citizen and not has_remedy:
                severity = "심각"
            elif strength == "강" and is_citizen:
                severity = "경고"
            elif strength == "강":
                continue  # 비-시민 대상 강한 제한 → F-03/F-05 영역
            elif strength == "중" and not has_remedy and is_citizen:
                severity = "주의"
            elif strength == "약" and is_citizen:
                severity = "개선"
            else:
                continue

            sub_check = "F-01-e" if not has_remedy else "F-01-a"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"권리 제한({strength})",
                        summary=(
                            f"{strength}한 권리 제한"
                            + (", 수범자 대상" if is_citizen else "")
                            + (", 구제수단 부재" if not has_remedy else "")
                        ),
                        fix_type="add_paragraph" if not has_remedy else "replace",
                        sub_check_id=sub_check,
                    ),
                )
            )
        return findings
