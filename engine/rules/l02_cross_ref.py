"""L-02 타법 조문 참조 (설계서 §3.2 L-02).

「법령명」 + "제N조" 매칭. MCP 인덱스를 활용해 단순 카운팅만 — 실재 여부는 L-03이 담당.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_CROSS_REF = re.compile(
    r"「([^」]+)」\s*제(\d+)조(?:의\d+)?(?:\s*제\d+항)?"
)
# FP: 인허가 의제 조문 — 다수 법률 참조가 본질
_PERMIT_DEEMED = re.compile(r"(인[\s·ㆍ]?허가.{0,10}의제|다른\s*법(률|령)에\s*따른\s*인[\s·ㆍ]?허가)")
# FP: 적용 제외·준용 등 표준 인용 컨텍스트
_STD_REFERENCE_TITLE = re.compile(
    r"(적용\s*제외|준용|결격\s*사유|회원의?\s*자격|자격|면제|비과세|감면"
    r"|특례|의제|편입|승계|소관|위탁"
    r"|채용시험|가점|우선\s*지원|우선순위|통합\s*조정"
    r"|적용.{0,3}특례|처분.{0,3}특례)"
)
# Method B (L-02_part01 inline 검증) — 지역·구역 정의 본문 신호
# R5 examples (FP):
#   L-02-011@건축법 제77조의15 (결합건축 대상지) - 상업지역·역세권·정비구역 인용
_REGION_DEFINITION_BODY = re.compile(
    r"(상업지역|역세권|정비구역|보호구역|진흥지구|특구|구역|지역).{0,40}따라\s*지정"
)


def _is_fp_article(art: Article) -> bool:
    if art.is_definition() or art.is_purpose() or art.is_penalty():
        return True
    title = art.title or ""
    text = art.full_text
    if _PERMIT_DEEMED.search(title) or _PERMIT_DEEMED.search(text[:300]):
        return True
    if _STD_REFERENCE_TITLE.search(title):
        return True
    if art.is_disqualification():
        return True
    # Method B: 지역·구역 정의 인용은 정상
    if _REGION_DEFINITION_BODY.search(text[:500]):
        return True
    return False


class L02CrossRef:
    pattern_id = "L-02"
    pattern_name = "타법 조문 참조"
    category = "적법성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            refs = _CROSS_REF.findall(art.full_text)
            if not refs:
                continue
            unique_laws = {r[0] for r in refs}
            if len(unique_laws) >= 7:
                severity = "경고"
            elif len(unique_laws) >= 5:
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
                        matched_text=f"{len(unique_laws)}개 법률",
                        summary=f"{art.number}에서 {len(unique_laws)}개 법률의 조문 참조",
                        fix_type="replace",
                    ),
                )
            )
        return findings
