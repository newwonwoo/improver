"""S-01 삽입조 과다 (법령 단위).

설계서 §3.2 S-01: 비율과 depth로 등급 산정 + depth ≥ 3인 개별 조문은 별도 finding.
"""
from __future__ import annotations

from ..schema import Article, Finding, Law
from ..structure import decompose  # noqa: F401 (R2 인프라 가용성 보장)
from .base import PatternResult, make_finding


class S01Insertion:
    pattern_id = "S-01"
    pattern_name = "삽입조 과다"
    category = "구조"

    def scan(self, law: Law) -> list[Finding]:
        if not law.articles:
            return []
        inserted = [a for a in law.articles if a.is_inserted]
        total = len(law.articles)
        ratio = len(inserted) / total * 100 if total else 0
        max_depth = max((a.insert_depth for a in law.articles), default=0)

        findings: list[Finding] = []
        idx = 0

        if max_depth >= 5 or ratio >= 40:
            severity = "심각"
        elif ratio >= 30 or max_depth >= 3:
            severity = "경고"
        elif ratio >= 20:
            severity = "주의"
        elif ratio >= 15:
            severity = "개선"
        else:
            severity = None

        if severity:
            idx += 1
            target = inserted[0] if inserted else law.articles[0]
            # S-01-b 삽입 밀도 (법령 단위)
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=target,
                        severity=severity,
                        matched_text=f"비율 {ratio:.1f}%, 최대깊이 {max_depth}",
                        summary=f"삽입조 {len(inserted)}/{total}건 ({ratio:.1f}%), 최대 깊이 {max_depth}",
                        fix_type="add_paragraph",
                        sub_check_id="S-01-b",
                    ),
                )
            )

        # S-01-a 삽입 깊이 — 개별 조문
        for art in inserted:
            if art.insert_depth >= 3:
                idx += 1
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=art,
                            severity="심각",
                            matched_text=art.number,
                            summary=f"{art.number}: 삽입 깊이 {art.insert_depth}단계",
                            fix_type="add_paragraph",
                            sub_check_id="S-01-a",
                        ),
                    )
                )
        return findings
