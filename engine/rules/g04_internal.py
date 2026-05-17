"""G-04 내부통제 — 감사원 5대 요소.

오탐 필터: 금융/기관설립/조합/공공기관 법령만 적용 (설계서 deep_patterns).
나머지는 비기관법으로 분류해 스킵.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_FIVE_ELEMENTS = {
    "통제환경": re.compile(r"(내부통제기준|통제환경|윤리강령|행동강령|윤리경영|윤리규정|조직구조)"),
    "위험평가": re.compile(r"(위험평가|위험관리|리스크|위험요인|위험분석)"),
    "통제활동": re.compile(r"(승인절차|직무분리|접근통제|결재|업무분장)"),
    "정보소통": re.compile(r"(보고체계|정보공유|경영공시|정보전달|의사소통)"),
    "모니터링": re.compile(r"(자체점검|자체평가|내부감사|모니터링|경영실적평가)"),
}

# 내부통제 적용 대상 법령 키워드
_APPLICABLE_HINTS = (
    "금융", "은행", "보험", "증권", "투자", "신용", "여신",
    "공사", "공단", "재단", "공공기관", "기금", "조합",
)


def _is_applicable(law_name: str) -> bool:
    return any(h in law_name for h in _APPLICABLE_HINTS)


class G04InternalControl:
    pattern_id = "G-04"
    pattern_name = "내부통제"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        if not _is_applicable(law.name):
            return []
        # 법령 전체 텍스트 기준 5요소 매칭
        full = "\n".join(art.full_text for art in law.articles)
        missing = [name for name, pat in _FIVE_ELEMENTS.items() if not pat.search(full)]
        met = len(_FIVE_ELEMENTS) - len(missing)
        if met >= 4:
            return []
        if met == 0:
            severity = "심각"
        elif met <= 2:
            severity = "경고"
        else:
            severity = "주의"

        # 가장 가까운 "업무지침|내부통제|관리규정" 조항을 대표 조문으로
        target = law.articles[0]
        for art in law.articles:
            if re.search(r"(업무지침|내부통제|관리규정|운영규정)", art.full_text):
                target = art
                break

        return [
            make_finding(
                self,
                1,
                PatternResult(
                    article=target,
                    severity=severity,
                    matched_text=f"5요소 중 {met}개 충족",
                    summary=f"내부통제 {met}/5 충족. 미충족: {', '.join(missing) or '없음'}",
                    fix_type="add_paragraph",
                ),
            )
        ]
