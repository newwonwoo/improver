"""S-02 위임 검증 — 단계1만 (포괄위임 식별).

설계서 §3.2 S-02: 단계2(하위법령 이행 확인)는 MCP/DB 연동이라 다음 PR.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_PRIMARY = re.compile(r"(대통령령|시행령|총리령|부령|시행규칙|고시)으?로\s*정(?:하|한|할|해|함)")
_VAGUE_SCOPE = re.compile(r"(필요한 사항|그 밖에|기타 사항|에 관한 사항)")


class S02Delegation:
    pattern_id = "S-02"
    pattern_name = "위임 검증"
    category = "구조"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if not _PRIMARY.search(art.full_text):
                continue
            vague_hits = _VAGUE_SCOPE.findall(art.full_text)
            if not vague_hits:
                # 구체적 위임 — 단계1에서는 정상 처리
                continue
            severity = "주의"  # 포괄위임 단독 → 주의 (설계서 §3.2 Case D)
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=", ".join(set(vague_hits)),
                        summary=f"포괄위임 {len(vague_hits)}건: 위임 범위 불명확",
                        fix_type="replace",
                    ),
                )
            )
        return findings
