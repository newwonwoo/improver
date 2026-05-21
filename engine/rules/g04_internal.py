"""G-04 내부통제 — 감사원 5대 요소.

오탐 필터: 금융/기관설립/조합/공공기관 법령만 적용 (설계서 deep_patterns).
나머지는 비기관법으로 분류해 스킵.
"""
from __future__ import annotations

import re

from ..structure import is_judicial_law, is_labor_welfare_law, decompose, ArticleType
from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_FIVE_ELEMENTS = {
    "통제환경": re.compile(r"(내부통제기준|통제환경|윤리강령|행동강령|윤리경영|윤리규정|조직구조)"),
    "위험평가": re.compile(r"(위험평가|위험관리|리스크|위험요인|위험분석|취약점\s*분석|취약점\s*평가)"),
    "통제활동": re.compile(r"(승인절차|직무분리|접근통제|결재|업무분장|업무지침)"),
    "정보소통": re.compile(r"(보고체계|정보공유|경영공시|정보전달|의사소통|보고\s*체제|보고\s*업무|내부\s*보고)"),
    "모니터링": re.compile(r"(자체점검|자체평가|내부감사|모니터링|경영실적평가|점검)"),
}

_SUBCHECK_MAP = {
    "통제환경": "G-04-a",
    "위험평가": "G-04-b",
    "통제활동": "G-04-c",
    "정보소통": "G-04-d",
    "모니터링": "G-04-e",
}

# 내부통제 적용 대상 법령 키워드
_APPLICABLE_HINTS = (
    "금융", "은행", "보험", "증권", "투자", "신용", "여신",
    "공사", "공단", "재단", "공공기관", "기금", "조합",
)

# TP 부스트: 내부통제기준 명시 → 진성 신호
_INTERNAL_CONTROL_EXPLICIT = re.compile(
    r"(내부통제기준|내부통제장치|내부통제시스템|준법감시인|이해상충관리|위험관리체계)"
)
# FP 필터: 폐지·설립 단문 조문
_REPEAL_ONLY = re.compile(r"이를\s*폐지한다|폐지된다")
_ESTABLISHMENT = re.compile(r"(~를|을|이)\s*설립한다|설립하여")
# FP 필터: 회계·세입 절차 조문
_ACCOUNTING_ONLY = re.compile(r"(세입|세출|회계연도|특별회계\s*설치|예산)")
_INTERNAL_ORG = re.compile(r"(임원|이사|이사회|감사|대표|직원)")


def _is_applicable(law_name: str) -> bool:
    return any(h in law_name for h in _APPLICABLE_HINTS)


class G04InternalControl:
    pattern_id = "G-04"
    pattern_name = "내부통제"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        # 사법·절차법령 — G-04 미적용 (verdict: 0 TP / 1 FP)
        if is_judicial_law(law.name):
            return []
        # 노동·복지·사회보험 법령 — G-04 미적용 (verdict: 0 TP / 8 FP)
        if is_labor_welfare_law(law.name):
            return []
        # SLM-level signal composition (docs/ENGINE_PRINCIPLES.md R1, R4)
        # Source: signal_candidates.json :: G-04 :: "내부통제 진성 신호 — 본문 명시키워드"
        # Rationale: "공단·기금·공사법" 이름만으론 내부통제 적용 대상 단정 불가.
        #            법령 본문에 진성 내부통제 키워드가 명시된 경우에만 진짜 적용 대상.
        # Examples (LLM verdicts that justify this gate):
        #   G-04-001@은행법 (TP — "내부통제기준 반영 의무" 명시)
        #   G-04-001@금융복합기업집단의감독에관한법률 (TP — "내부통제정책 수립")
        #   G-04-001@한국투자공사법 (TP — "내부통제기준 정하여야")
        #   G-04-001@농업협동조합법 (TP — "내부통제기준 및 준법감시인")
        #   G-04-001@부동산투자회사법 (TP — "내부통제기준 제정")
        # Counter-examples (FPs this gate suppresses):
        #   G-04-001@한국가스공사법 (FP — 단순 설립조문)
        #   G-04-001@공공자금관리기금법 (FP — 기금 통합관리 목적)
        #   G-04-001@대한석탄공사법 (FP — 자원개발 촉진 목적)
        if not _is_applicable(law.name):
            return []
        if len(law.articles) < 5:
            return []
        # 목적·정의조문은 FP 제외
        articles = [
            a for a in law.articles
            if not a.is_purpose() and not a.is_definition()
            # 폐지 단문 제외
            and not _REPEAL_ONLY.search(a.full_text)
        ]
        # 회계·세입만 있는 조문도 제외
        articles = [
            a for a in articles
            if not (_ACCOUNTING_ONLY.search(a.full_text) and not _INTERNAL_ORG.search(a.full_text))
        ]
        if not articles:
            return []
        # 법령 전체 텍스트 기준 5요소 매칭
        full = "\n".join(art.full_text for art in articles)

        # R1 (signal composition): 적용 후보 법령이라 해도,
        # 본문 어디에도 진성 내부통제 신호가 없으면 발화하지 않는다.
        # 진성 신호 := 5요소 중 ≥1개 매칭 OR _INTERNAL_CONTROL_EXPLICIT 매칭
        has_explicit_signal = bool(_INTERNAL_CONTROL_EXPLICIT.search(full))
        elements_matched = [name for name, pat in _FIVE_ELEMENTS.items() if pat.search(full)]
        if not has_explicit_signal and len(elements_matched) == 0:
            # 단순히 "공단·기금·공사" 이름만 가진 법령 — 적용 대상 아님
            return []

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
        target = None
        for art in law.articles:
            if re.search(r"(업무지침|내부통제|관리규정|운영규정)", art.full_text):
                target = art
                break
            # TP 부스트: 명시적 내부통제 키워드 조문
            if _INTERNAL_CONTROL_EXPLICIT.search(art.full_text):
                target = art
                break
        # SLM verdict: PURPOSE 조문을 target으로 잡으면 15건 모두 FP
        # → 진성 내부통제 조문이 없으면 발화 자체를 안 함
        if target is None:
            return []
        if decompose(target).type == ArticleType.PURPOSE:
            return []

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
                    sub_check_id=_SUBCHECK_MAP[missing[0]] if missing else None,
                ),
            )
        ]
