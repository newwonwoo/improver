"""L-03 참조 끊김 (엔진 설계서 §3.2 + §5.2).

「법령명」 제N조 참조에 대해 MCP 인덱스로 실재 여부 확인.
폐지/제명변경/조문 삭제별로 등급 분기.
"""
from __future__ import annotations

import re

from ..mcp import LawIndex, load_default_index
from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_CROSS_REF = re.compile(r"「([^」]+)」\s*제(\d+)조(?:의\d+)?")


class L03BrokenRef:
    pattern_id = "L-03"
    pattern_name = "참조 끊김"
    category = "적법성"

    def __init__(self, index: LawIndex | None = None):
        self._index = index

    def _idx(self) -> LawIndex:
        if self._index is None:
            self._index = load_default_index()
        return self._index

    def scan(self, law: Law) -> list[Finding]:
        index = self._idx()
        findings: list[Finding] = []
        idx = 0
        seen: set[tuple[str, str, str]] = set()
        for art in law.articles:
            for m in _CROSS_REF.finditer(art.full_text):
                ref_law = m.group(1)
                ref_art = m.group(2)
                key = (art.article_id, ref_law, ref_art)
                if key in seen:
                    continue
                seen.add(key)
                result = index.has_article(ref_law, ref_art)
                if result.status == "exists":
                    continue
                if result.status == "law_repealed":
                    severity = "심각"
                    summary = (
                        f"폐지 법령 인용: 「{ref_law}」 제{ref_art}조"
                        + (f" — 현행: {result.current_law_name}" if result.current_law_name else "")
                    )
                elif result.status == "law_renamed":
                    severity = "주의"
                    summary = f"제명변경 미반영: 「{ref_law}」 → 「{result.current_law_name}」"
                elif result.status == "not_found":
                    severity = "경고"
                    summary = f"조문 부재: 「{ref_law}」 제{ref_art}조 — 현행법에서 삭제됨"
                else:  # unknown — 인덱스에 없음
                    continue
                idx += 1
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=art,
                            severity=severity,
                            matched_text=f"「{ref_law}」 제{ref_art}조",
                            summary=summary,
                            fix_type="replace",
                        ),
                    )
                )
        return findings
