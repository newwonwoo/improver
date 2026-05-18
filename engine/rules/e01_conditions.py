"""E-01 조건 중첩 (엔진 설계서 §3.2).

조건 도입어("경우/때") + 접속사("및/또는/이고") 카운팅으로 단계 추정.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_CONDITION_LEAD = re.compile(r"(경우|때|요건)(?:에는|에)?")
_AND_OR = re.compile(r"(및|또는|이고|이며|하고|하며)")
_NESTED_HINT = re.compile(r"(에 해당하는 경우로서|충족하고|갖추어야 하며|모두 충족|다음 각 호의)")


class E01Conditions:
    pattern_id = "E-01"
    pattern_name = "조건 중첩"
    category = "효율성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            text = art.full_text
            cond = len(_CONDITION_LEAD.findall(text))
            link = len(_AND_OR.findall(text))
            nested = len(_NESTED_HINT.findall(text))
            stages = nested + (cond // 2) + (link // 3)
            if stages < 3:
                continue
            if stages >= 5:
                severity = "심각"
            elif stages >= 4:
                severity = "경고"
            else:
                severity = "주의"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"조건 {stages}단계",
                        summary=f"조건 {stages}단계 중첩",
                        fix_type="replace",
                        sub_check_id="E-01-a",
                    ),
                )
            )
        return findings
