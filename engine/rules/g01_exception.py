"""G-01 예외·단서 (설계서 §3.2 G-01)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_DANSEO = re.compile(r"다만[,\s]")
_VAGUE_EXC = re.compile(r"대통령령으로 정하는 (경우|사항)을? 제외")


class G01Exception:
    pattern_id = "G-01"
    pattern_name = "예외·단서"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            text = art.full_text
            danseo_count = len(_DANSEO.findall(text))
            has_vague_exc = bool(_VAGUE_EXC.search(text))

            if danseo_count >= 3:
                severity = "심각"
            elif danseo_count == 2:
                severity = "경고"
            elif danseo_count == 1 and has_vague_exc:
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
                        matched_text=f"단서 {danseo_count}회",
                        summary=f"단서 {danseo_count}회 중첩"
                        + (" + 포괄 예외" if has_vague_exc else ""),
                        fix_type="replace",
                    ),
                )
            )
        return findings
