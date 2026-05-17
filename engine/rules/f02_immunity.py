"""F-02 면책 조항 (설계서 §3.2 F-02)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_PATTERN_A = re.compile(r"(책임을 지지 아니한다|책임이 없다|책임을 면한다|면책)")
_PATTERN_B = re.compile(r"(손해를 배상하지 아니한다)")
_PATTERN_C = re.compile(r"(일체의|모든|어떠한)[^.]{0,40}(책임)")
_EXCEPTION = re.compile(r"(고의\s*(또는|또는\s*중과실|·중과실)|고의·중과실|중과실 제외)")


class F02Immunity:
    pattern_id = "F-02"
    pattern_name = "면책 조항"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty():
                continue
            text = art.full_text
            is_full = bool(_PATTERN_C.search(text))
            is_partial = bool(_PATTERN_A.search(text) or _PATTERN_B.search(text))
            if not (is_full or is_partial):
                continue
            has_exception = bool(_EXCEPTION.search(text))

            if is_full and not has_exception:
                severity = "심각"
            elif is_partial and not has_exception:
                severity = "경고"
            elif is_partial and has_exception:
                severity = "주의"
            else:
                severity = "양호"

            if severity == "양호":
                continue

            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text="면책",
                        summary=(
                            ("전면 면책" if is_full else "부분 면책")
                            + (" (고의·중과실 예외 없음)" if not has_exception else " (범위 불명확)")
                        ),
                        fix_type="proviso" if is_full else "replace",
                    ),
                )
            )
        return findings
