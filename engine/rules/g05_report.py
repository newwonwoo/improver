"""G-05 보고 의무 — 주기/양식/방법/제재 4요소."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


# 실질 보고 의무만 (단순 제출·통보는 제외)
_REPORT_OBLIG = re.compile(r"(보고하여야\s*한다|보고를?\s*하여야|정기적으로\s*보고)")
_ELEMENTS = {
    "보고 주기": re.compile(r"(매년|분기|반기|매월|매분기|매반기|수시|정기)"),
    "보고 양식": re.compile(r"(별지|서식|양식|보고서)"),
    "보고 방법": re.compile(r"(전자적\s*방법|서면|정보통신망|온라인|문서)"),
    "지연 제재": re.compile(r"(과태료|벌금|징역|영업정지|취소|제재)"),
}

_SUBCHECK_MAP = {
    "보고 주기": "G-05-a",
    "보고 양식": "G-05-b",
    "보고 방법": "G-05-c",
    "지연 제재": "G-05-d",
}

# FP 필터: 내부 보고 (감사원, 국회 보고 등 상위기관 포함)
_INTERNAL_REPORT = re.compile(
    r"(국회에?\s*보고|감사원에?\s*보고|대통령에게?\s*보고|소관\s*위원회|국무회의)"
)
# FP 필터: 행정 내부 보고 — 주체가 공무원/소속직원인 경우만
# 주의: '장관에게 보고하여야' 자체는 외부 수탁기관도 하므로 주체 확인 필요
_INTERNAL_ADMIN_REPORT = re.compile(
    r"(소속\s*공무원|소속\s*직원"
    r"|공무원은.{0,30}보고하여야|직원은.{0,30}보고하여야"
    r"|물품.{0,5}공무원|물품관리관에게.{0,10}보고"
    r"|직무위반.{0,10}보고|이탈.{0,10}보고|징계.{0,10}보고)"
)
# FP 필터: 결과 보고 → 심의/의결 후 단순 통지
_RESULT_REPORT = re.compile(r"(결과를?\s*보고|결과를?\s*알려|현황을?\s*보고)")


class G05Report:
    pattern_id = "G-05"
    pattern_name = "보고 의무"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty() or art.is_definition() or art.is_purpose():
                continue
            text = art.full_text
            if not _REPORT_OBLIG.search(text):
                continue
            # 내부/상위기관 보고는 절차 요건 적용 불필요
            if _INTERNAL_REPORT.search(text):
                continue
            # 행정 내부 보고 (공무원→장관, 기관장→부처) — 외부 의무 아님
            if _INTERNAL_ADMIN_REPORT.search(text):
                continue
            # 단순 결과 통보
            if _RESULT_REPORT.search(text) and not _REPORT_OBLIG.search(text.replace("결과를 보고", "")):
                continue
            missing = [name for name, pat in _ELEMENTS.items() if not pat.search(text)]
            met = len(_ELEMENTS) - len(missing)
            if met >= 2:
                continue  # 양호 (2개 이상 요소 충족)
            # 제재 요소가 없으면 한 단계 상향
            missing_sanction = "지연 제재" in missing
            if met == 0:
                severity = "경고"
            elif missing_sanction:
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
                        matched_text="보고하여야 한다",
                        summary=f"보고 규정 {met}/4 충족. 미충족: {', '.join(missing)}",
                        fix_type="add_paragraph",
                        sub_check_id=_SUBCHECK_MAP[missing[0]] if missing else None,
                    ),
                )
            )
        return findings
