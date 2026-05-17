"""S-04 열거 과다 (항 단위 호 개수)."""
from __future__ import annotations

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


class S04Enumeration:
    pattern_id = "S-04"
    pattern_name = "열거 과다"
    category = "구조"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            for para in art.paragraphs:
                n = len(para.items)
                if n < 10:
                    continue
                if n >= 30:
                    severity = "심각"
                elif n >= 20:
                    severity = "경고"
                elif n >= 15:
                    severity = "주의"
                else:
                    severity = "개선"
                idx += 1
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=art,
                            severity=severity,
                            matched_text=f"호 {n}개",
                            summary=f"{art.number} {para.number or ''}: 호 {n}개 나열",
                            fix_type="add_paragraph",
                        ),
                    )
                )
        return findings
