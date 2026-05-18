"""G-05 보고 의무 — 주기/양식/방법/제재 4요소."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_REPORT_OBLIG = re.compile(r"(보고하여야|제출하여야|통보하여야)")
_ELEMENTS = {
    "보고 주기": re.compile(r"(매년|분기|반기|매월|매분기|매반기|수시)"),
    "보고 양식": re.compile(r"(별지|서식|양식)"),
    "보고 방법": re.compile(r"(전자적 방법|서면|정보통신망|온라인)"),
    "지연 제재": re.compile(r"(과태료|벌금|징역|제재|영업정지)"),
}

_SUBCHECK_MAP = {
    "보고 주기": "G-05-a",
    "보고 양식": "G-05-b",
    "보고 방법": "G-05-c",
    "지연 제재": "G-05-d",
}


class G05Report:
    pattern_id = "G-05"
    pattern_name = "보고 의무"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if not _REPORT_OBLIG.search(art.full_text):
                continue
            text = art.full_text
            missing = [name for name, pat in _ELEMENTS.items() if not pat.search(text)]
            met = len(_ELEMENTS) - len(missing)
            if met >= 3:
                continue  # 양호
            severity = "경고" if met == 0 else "주의"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text="보고하여야 한다",
                        summary=f"보고 규정 {met}/4 충족. 미충족: {', '.join(missing)}",
                        fix_type="add_paragraph",
                        sub_check_id=_SUBCHECK_MAP[missing[0]] if missing else None,
                    ),
                )
            )
        return findings
