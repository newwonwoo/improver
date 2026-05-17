"""E-02 서식 관련 (법령 단위, 별지 카운팅)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_FORM = re.compile(r"별지 제\d+호")


class E02Form:
    pattern_id = "E-02"
    pattern_name = "서식 관련"
    category = "효율성"

    def scan(self, law: Law) -> list[Finding]:
        forms: set[str] = set()
        target = None
        for art in law.articles:
            for m in _FORM.finditer(art.full_text):
                forms.add(m.group(0))
                target = target or art
        n = len(forms)
        if n < 5:
            return []
        if n >= 20:
            severity = "심각"
        elif n >= 10:
            severity = "경고"
        else:
            severity = "주의"
        return [
            make_finding(
                self,
                1,
                PatternResult(
                    article=target,
                    severity=severity,
                    matched_text=f"서식 {n}종",
                    summary=f"별지 서식 {n}종 사용",
                    fix_type="sub_legislation",
                ),
            )
        ]
