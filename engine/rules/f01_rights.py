"""F-01 권리 제한 + 구제수단 부재 (설계서 §3.2 F-01)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_STRONG = re.compile(
    r"(금지한다|할 수 없다|하지 못한다|박탈|취소한다|정지한다|자격을 상실|효력을 잃|아니 된다)"
)
_MID = re.compile(r"(제한한다|제한할 수 있다|배제|적용하지 아니한다|거부할 수 있다)")
_WEAK = re.compile(r"(제한|조건을 붙일 수 있다)")
_REMEDY = re.compile(r"(이의신청|이의 신청|구제|청문|소명|행정소송|행정심판|불복)")
_OBLIGOR = re.compile(r"(국민|소비자|이용자|가입자|근로자|당사자|신청인)")


class F01Rights:
    pattern_id = "F-01"
    pattern_name = "권리 제한"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        articles = law.articles
        for i, art in enumerate(articles):
            if art.is_penalty():
                continue
            text = art.full_text
            if _STRONG.search(text):
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
            is_consumer = bool(_OBLIGOR.search(text))

            if strength == "강" and is_consumer and not has_remedy:
                severity = "심각"
            elif strength == "강":
                severity = "경고"
            elif strength == "중":
                severity = "주의"
            else:
                severity = "개선"

            # 서브체크: 구제수단 부재 → F-01-e, 그 외 강한 제한 → F-01-a
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
                            + (", 수범자 대상" if is_consumer else "")
                            + (", 구제수단 부재" if not has_remedy else "")
                        ),
                        fix_type="add_paragraph" if not has_remedy else "replace",
                        sub_check_id=sub_check,
                    ),
                )
            )
        return findings
