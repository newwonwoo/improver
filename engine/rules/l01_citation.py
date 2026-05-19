"""L-01 인용 법령 (엔진 설계서 §3.2).

「」 안의 법령 인용 수가 한 조문에서 5건↑ → 주의 (과도한 타법 의존).
정확한 폐지/제명 확인은 MCP 연동 필요 → 다음 PR.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding

_CITE_PAT = re.compile(r"「([^」]+)」")
# TP 컨텍스트: 인허가의제·특례·금지 조문 — 과도한 인용이 실질 결함
_TP_CONTEXT = re.compile(r"(인[\s·ㆍ]?허가.{0,10}의제|특례\s*규정|금지\s*행위|이\s*법에\s*따른\s*의무)")
# FP 컨텍스트: 법제상 불가피한 타법 인용 조문 유형
_FP_CONTEXT = re.compile(
    r"(결격\s*사유|취업\s*제한|징계\s*부가금|감면\s*대상|지급\s*대상|중복\s*수급"
    r"|회원의?\s*자격|비과세|적용\s*제외|준용한다|준용하는|회원\s*가입)"
)
_FP_TITLE = re.compile(
    r"(승계|회원의?\s*자격|비과세|면제|적용\s*제외|준용|회원\s*가입"
    r"|결격\s*사유|감면|특별\s*공제|공제\s*대상)"
)


def _is_fp_article(art: Article) -> bool:
    """L-01 FP 필터 — 불가피한 타법 인용 조문."""
    if art.is_definition() or art.is_penalty() or art.is_purpose():
        return True
    if art.is_disqualification():
        return True
    title = art.title or ""
    if _FP_TITLE.search(title):
        return True
    text = art.full_text
    if _FP_CONTEXT.search(text):
        return True
    return False


class L01Citation:
    pattern_id = "L-01"
    pattern_name = "인용 법령"
    category = "적법성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            cites = _CITE_PAT.findall(art.full_text)
            # 법령명만 카운트 — 동일 법령명은 1회로
            laws = {c for c in cites if c.endswith("법") or c.endswith("법률") or "관한 법" in c}
            if len(laws) < 6:
                continue
            # TP 부스트: 의제·특례 조문의 과다 인용은 한 단계 상향
            has_tp_context = bool(_TP_CONTEXT.search(art.full_text))
            if len(laws) >= 10:
                severity = "심각" if has_tp_context else "경고"
            elif len(laws) >= 8:
                severity = "경고" if has_tp_context else "주의"
            else:
                severity = "주의" if has_tp_context else "개선"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"{len(laws)}개 법률",
                        summary=f"한 조문에 {len(laws)}개 법률 인용 — 독해 곤란"
                        + (" (의제·특례 조문)" if has_tp_context else ""),
                        fix_type="replace",
                    ),
                )
            )
        return findings
