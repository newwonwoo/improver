"""G-03 감독 권한 (엔진 설계서 §3.2 + 서브체크 5요소).

감독 조항 식별 후 범위/주기/방법/공개/시정권 5요소 충족 여부 점수화.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_SUPERVISE = re.compile(r"(감독|감시|단속)한다")
_ELEMENTS = {
    "감독 범위": re.compile(r"(다음 각 호|업무|회계|운영|재산)"),
    "감독 주기": re.compile(r"(연 \d|분기|반기|매년|매월|수시)"),
    "감독 방법": re.compile(r"(서면|현장|보고서|조사)"),
    "결과 공개": re.compile(r"(공시|공개|국회에 보고|국회 보고)"),
    "시정 명령권": re.compile(r"(시정명령|시정을 명할|시정을 요구|개선명령)"),
}


class G03Supervision:
    pattern_id = "G-03"
    pattern_name = "감독 권한"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if not _SUPERVISE.search(art.full_text):
                continue
            text = art.full_text
            missing = [name for name, pat in _ELEMENTS.items() if not pat.search(text)]
            met = len(_ELEMENTS) - len(missing)
            if met >= 4:
                continue  # 양호
            if met == 0:
                severity = "심각"
            elif met <= 2:
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
                        matched_text="감독한다",
                        summary=f"감독 규정 {met}/5 충족. 미충족: {', '.join(missing)}",
                        fix_type="add_paragraph",
                    ),
                )
            )
        return findings
