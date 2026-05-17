"""S-03 모호 표현 (엔진 설계서 §3.2)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


VAGUE_KEYWORDS: list[str] = [
    "상당한",
    "적절한",
    "적정한",
    "필요한 경우",
    "필요하다고 인정",
    "정당한 사유",
    "합리적인",
    "중대한",
    "현저한",
    "현저히",
    "그 밖에",
    "그 밖의",
    "기타",
]

# FPC: "그 밖에 ... 대통령령으로" 같은 위임 결합은 S-02에서 잡으므로 제외
_DELEG_TAIL = re.compile(r"(그 밖에|기타)[^.]{0,40}(대통령령|시행령|부령|총리령|시행규칙)")


def _find_keywords(text: str) -> list[str]:
    hits: list[str] = []
    for kw in VAGUE_KEYWORDS:
        if kw in text:
            hits.append(kw)
    return hits


class S03Vague:
    pattern_id = "S-03"
    pattern_name = "모호 표현"
    category = "구조"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_definition() or art.is_penalty():
                continue
            text = art.full_text
            # 위임 결합 표현은 한 번씩만 제거
            cleaned = _DELEG_TAIL.sub("", text)
            hits = _find_keywords(cleaned)
            if not hits:
                continue

            count = len(hits)
            is_oblig = art.is_obligation()
            if is_oblig and count >= 2:
                severity = "심각"
            elif count >= 3:
                severity = "경고"
            elif count == 2:
                severity = "주의"
            else:
                severity = "개선"

            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=", ".join(hits),
                        summary=f"모호 표현 {count}건: {', '.join(hits)}",
                        fix_type="replace",
                        sub_check_id="S-03-a",
                    ),
                )
            )
        return findings
