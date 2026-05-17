"""F-03 처분·명령 (설계서 §3.2 F-03)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_STRONG = re.compile(r"(영업정지|인허가 취소|등록 취소|폐쇄명령|해임요구|인가 취소|허가 취소)")
_MID = re.compile(r"(시정명령|과징금|과태료|업무정지)")
_WEAK = re.compile(r"(시정권고|개선명령|주의|경고)")
_HEARING = re.compile(r"(청문|의견제출|의견 제출|이의신청|이의 신청)")
_STANDARD = re.compile(r"(별표|기준|등급)")


class F03Disposition:
    pattern_id = "F-03"
    pattern_name = "처분·명령"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0

        # 법령 전체에서 청문 절차 존재 여부 (다른 조문에 있을 수 있음)
        has_hearing_in_law = any(_HEARING.search(a.full_text) for a in law.articles)

        for art in law.articles:
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

            has_standard = bool(_STANDARD.search(text))

            if strength == "강" and not has_hearing_in_law:
                severity = "심각"
            elif strength == "강" and not has_standard:
                severity = "경고"
            elif strength == "중" and not has_hearing_in_law:
                severity = "주의"
            elif strength == "약":
                severity = "개선"
            else:
                severity = "양호"

            if severity == "양호":
                continue

            idx += 1
            details = []
            if not has_hearing_in_law:
                details.append("청문 부재")
            if not has_standard:
                details.append("기준 미규정")
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"{strength}한 처분",
                        summary=f"{strength}한 처분 + {', '.join(details) or '비례원칙 검토'}",
                        fix_type="add_paragraph",
                    ),
                )
            )
        return findings
