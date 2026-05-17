"""L-02 타법 조문 참조 (설계서 §3.2 L-02).

「법령명」 + "제N조" 매칭. MCP 인덱스를 활용해 단순 카운팅만 — 실재 여부는 L-03이 담당.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_CROSS_REF = re.compile(
    r"「([^」]+)」\s*제(\d+)조(?:의\d+)?(?:\s*제\d+항)?"
)


class L02CrossRef:
    pattern_id = "L-02"
    pattern_name = "타법 조문 참조"
    category = "적법성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            refs = _CROSS_REF.findall(art.full_text)
            if not refs:
                continue
            unique_laws = {r[0] for r in refs}
            if len(unique_laws) >= 5:
                severity = "경고"
            elif len(unique_laws) >= 3:
                severity = "주의"
            else:
                continue
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"{len(unique_laws)}개 법률",
                        summary=f"{art.number}에서 {len(unique_laws)}개 법률의 조문 참조",
                        fix_type="replace",
                    ),
                )
            )
        return findings
