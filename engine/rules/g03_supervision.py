"""G-03 감독 권한 (엔진 설계서 §3.2 + 서브체크 5요소).

감독 조항 식별 후 범위/주기/방법/공개/시정권 5요소 충족 여부 점수화.
외부 감독(기관·단체 대상)만 적용; 내부 지휘감독은 제외.
"""
from __future__ import annotations

import re

from ..structure import is_judicial_law, is_criminal_special_law, is_military_law, is_blacklisted
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

_SUBCHECK_MAP = {
    "감독 범위": "G-03-a",
    "감독 주기": "G-03-b",
    "감독 방법": "G-03-c",
    "결과 공개": "G-03-d",
    "시정 명령권": "G-03-e",
}

# FP 필터: 내부 지휘감독 — 소속 직원·공무원 대상
_INTERNAL_COMMAND = re.compile(
    r"(소속\s*(공무원|직원|군인|경찰관|대원|판사|검사)"
    r"|명을\s*받아.{0,20}감독"
    r"|지휘[ㆍ·]?감독.{0,20}(소속|하급))"
)
# FP 필터: 위임·위탁받은 자 감독 (수직적 위임사무)
_DELEGATED_SUPERVISE = re.compile(
    r"(위임|위탁).{0,30}(받은\s*자를?|기관을?).{0,20}(지휘|감독)"
)
# TP: 외부 법인·단체에 대한 감독 (주무관청, 장관 → 법인·협회·조합 대상)
_EXTERNAL_TARGET = re.compile(
    r"(법인|협회|조합|공단|재단|기금|학교|의료기관|사업자|업자|자격자)"
)


def _is_fp_article(art: Article) -> bool:
    if art.is_definition() or art.is_purpose() or art.is_penalty():
        return True
    text = art.full_text
    # 내부 지휘감독 (소속 직원·공무원 대상) — FP
    if _INTERNAL_COMMAND.search(text):
        return True
    # 위임·위탁받은 자 지휘감독 — FP
    if _DELEGATED_SUPERVISE.search(text):
        return True
    return False


def _subcheck_for_missing(missing: list[str]) -> str | None:
    return _SUBCHECK_MAP[missing[0]] if missing else None


class G03Supervision:
    pattern_id = "G-03"
    pattern_name = "감독 권한"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "G-03"):
            return []
        # Domain gates — each shows 0 TP / N FP
        if is_judicial_law(law.name):           # 0/28
            return []
        if is_criminal_special_law(law.name):   # 0/5
            return []
        if is_military_law(law.name):           # 0/8
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if not _SUPERVISE.search(art.full_text):
                continue
            if _is_fp_article(art):
                continue
            text = art.full_text
            # 외부 감독 대상이 없으면 skip (내부 지휘만 남은 경우)
            if not _EXTERNAL_TARGET.search(text):
                continue
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
                        sub_check_id=_subcheck_for_missing(missing),
                    ),
                )
            )
        return findings
