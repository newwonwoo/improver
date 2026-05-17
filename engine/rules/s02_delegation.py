"""S-02 위임 검증 — 단계1 (포괄위임) + 단계2 (하위법령 이행).

설계서 §3.2 S-02: MCP 인덱스 사용 가능 시 시행령 이행 여부도 함께 판정.
"""
from __future__ import annotations

import re

from ..mcp import LawIndex, load_default_index
from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_PRIMARY = re.compile(r"(대통령령|시행령|총리령|부령|시행규칙|고시)으?로\s*정(?:하|한|할|해|함)")
_VAGUE_SCOPE = re.compile(r"(필요한 사항|그 밖에|기타 사항|에 관한 사항)")


class S02Delegation:
    pattern_id = "S-02"
    pattern_name = "위임 검증"
    category = "구조"

    def __init__(self, index: LawIndex | None = None, *, check_decree: bool = True):
        self._index = index
        self._check_decree = check_decree

    def _idx(self) -> LawIndex | None:
        if self._index is None and self._check_decree:
            try:
                self._index = load_default_index()
            except Exception:
                self._check_decree = False
                return None
        return self._index

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        index = self._idx() if self._check_decree else None

        # 단계1: 포괄위임 식별
        delegating: list[Article] = []
        for art in law.articles:
            if not _PRIMARY.search(art.full_text):
                continue
            delegating.append(art)
            vague_hits = _VAGUE_SCOPE.findall(art.full_text)
            if not vague_hits:
                continue
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity="주의",
                        matched_text=", ".join(set(vague_hits)),
                        summary=f"포괄위임 {len(vague_hits)}건: 위임 범위 불명확",
                        fix_type="replace",
                    ),
                )
            )

        # 단계2: 하위법령 이행 검증 (MCP 인덱스)
        if index is None or not delegating:
            return findings

        parent = index.find(law.name)
        if parent is None:
            return findings
        if not parent.get("has_enforcement_decree"):
            # 시행령 자체 없음 → 위임 다수면 심각
            if len(delegating) >= 3:
                idx += 1
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=delegating[0],
                            severity="심각",
                            matched_text="시행령 부재",
                            summary=f"위임 {len(delegating)}건이 있으나 시행령 자체 미제정",
                            fix_type="sub_legislation",
                        ),
                    )
                )
            return findings

        decree = index.decree_for(law.name)
        if decree is None:
            return findings
        decree_arts = set(decree.get("article_numbers", []))
        unmatched = 0
        for art in delegating:
            base = art.number_raw
            # 근방 ±3조 매칭 (휴리스틱)
            try:
                b = int(base)
            except ValueError:
                continue
            near = any(
                a.isdigit() and abs(int(a) - b) <= 3 for a in decree_arts
            )
            if not near:
                unmatched += 1
                idx += 1
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=art,
                            severity="경고",
                            matched_text=art.number,
                            summary=f"{art.number} 위임 대응 시행령 조문 미확인",
                            fix_type="sub_legislation",
                        ),
                    )
                )
        if unmatched >= 3 and findings:
            findings[-unmatched].severity = "심각"
            findings[-unmatched].severity_score = 10
            findings[-unmatched].summary = (
                f"위임 {unmatched}건 미이행: 시행령에 대응 조문 다수 누락"
            )
        return findings
