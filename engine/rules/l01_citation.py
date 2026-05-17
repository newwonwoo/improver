"""L-01 인용 법령 (엔진 설계서 §3.2).

「」 안의 법령 인용 수가 한 조문에서 5건↑ → 주의 (과도한 타법 의존).
정확한 폐지/제명 확인은 MCP 연동 필요 → 다음 PR.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding

_CITE_PAT = re.compile(r"「([^」]+)」")


class L01Citation:
    pattern_id = "L-01"
    pattern_name = "인용 법령"
    category = "적법성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            cites = _CITE_PAT.findall(art.full_text)
            # 법령명만 카운트 — 동일 법령명은 1회로
            laws = {c for c in cites if c.endswith("법") or c.endswith("법률") or "관한 법" in c}
            if len(laws) < 5:
                continue
            severity = "경고" if len(laws) >= 10 else "주의"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"{len(laws)}개 법률",
                        summary=f"한 조문에 {len(laws)}개 법률 인용 — 독해 곤란",
                        fix_type="replace",
                    ),
                )
            )
        return findings
