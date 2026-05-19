"""L-03 참조 끊김 (엔진 설계서 §3.2 + §5.2).

「법령명」 제N조 참조에 대해 MCP 인덱스로 실재 여부 확인.
보수적 운영: article_count < 40인 법령은 데이터 불완전 가능성 → skip.
폐지법령 인용만은 무조건 보고.
"""
from __future__ import annotations

import re

from ..mcp import LawIndex, load_default_index
from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_CROSS_REF = re.compile(r"「([^」]+)」\s*제(\d+)조(?:의\d+)?")
# FP 필터: 정의·목적 조문 내 인용은 검증 생략
_DEFINITION_CONTEXT = re.compile(r'"[^"]+"\s*(이)?란\s*.{0,50}말한다')
# 최소 조문 수 — 이 이상이어야 인덱스가 신뢰할 수 있다
_MIN_ART_COUNT_FOR_NOT_FOUND = 40


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
            if art.is_definition() or art.is_purpose():
                continue
            text = art.full_text
            for m in _CROSS_REF.finditer(text):
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
                    # 인덱스가 완전한 법령만 not_found 보고 (불완전 인덱스 오탐 방지)
                    entry = index.find(ref_law)
                    if entry is None:
                        continue
                    art_count = entry.get("article_count") or len(entry.get("article_numbers", []))
                    if art_count < _MIN_ART_COUNT_FOR_NOT_FOUND:
                        continue
                    severity = "경고"
                    summary = f"조문 부재: 「{ref_law}」 제{ref_art}조 — 현행법에서 삭제됨"
                else:  # unknown
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
