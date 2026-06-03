"""G-05 보고 의무 — 주기/양식/방법/제재 4요소."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ActionKind
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
    r"(국회.{0,20}보고|국회.{0,20}제출|감사원.{0,10}보고|대통령에게?\s*보고"
    r"|소관\s*(상임)?\s*위원회|국무회의"
    r"|국회의장|국정감사|국정조사)"
)
# FP 필터: 학술·교육 내부 보고
_ACADEMIC_INTERNAL = re.compile(r"(총장이?\s*정하고.{0,30}보고|학위과정|교육과정)")
# Method B (Claude inline G-05_part01 검증) — 행정청간 통보
# R5 examples (FP):
#   G-05-011@가족관계등록법 (법무부 → 시읍면장 행정통보)
#   G-05-005@개발제한구역법 (시·도지사 → 국토부장관 행정보고)
#   G-05-004@가축이력관리법 (장관 → 신청인 행정통보)
_INTER_AGENCY_NOTIFICATION = re.compile(
    r"(장관|시ㆍ?도지사|시장|군수|구청장|단장|위원장)"
    r".{0,40}(시읍면|시ㆍ?읍ㆍ?면의?\s*장|관계\s*기관|관할\s*기관"
    r"|상위\s*기관|국토교통부장관|보건복지부장관|질병관리청장|신청인|신청\s*대상자)"
    r".{0,30}(보고|통보)"
)
# 결산·연차 단발 보고
_ANNUAL_REPORT_TITLE = re.compile(r"(결산보고|연차보고|연도\s*보고|연간\s*보고|업무보고)")
# 사업자 → 발주자 계약상 통보
_CONTRACT_NOTIFICATION = re.compile(
    r"(사업자|건설사업자|수급인).{0,30}발주자에게.{0,10}(통보|제출|보고)"
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
            # R2 ActionKind 보강: 키워드 OR 구조화 REPORT 액션
            d = decompose(art)
            has_report_action = ActionKind.REPORT in d.actions
            if not (_REPORT_OBLIG.search(text) or has_report_action):
                continue
            # 내부/상위기관 보고는 절차 요건 적용 불필요
            if _INTERNAL_REPORT.search(text):
                continue
            # 행정 내부 보고 (공무원→장관, 기관장→부처) — 외부 의무 아님
            if _INTERNAL_ADMIN_REPORT.search(text):
                continue
            # 학술·교육 내부 보고 — 외부 규제 아님
            if _ACADEMIC_INTERNAL.search(text):
                continue
            # Method B: 행정청간 통보 (시읍면·관계기관·상위기관·신청인 등)
            if _INTER_AGENCY_NOTIFICATION.search(text):
                continue
            # 결산·연차 단발 보고
            if _ANNUAL_REPORT_TITLE.search(art.title or ""):
                continue
            # 사업자 → 발주자 계약상 통보
            if _CONTRACT_NOTIFICATION.search(text):
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
