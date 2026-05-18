"""E-03 아날로그 잔재 (전자 대안 부재 판별)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_STRONG = re.compile(r"(서면으로|날인|인감|대면하여|직접 출석)")
_MID = re.compile(r"(등기우편|내용증명|우편으로)")
_WEAK = re.compile(r"(서면|문서)")
_DIGITAL = re.compile(r"(전자문서|전자적 방법|정보통신망|전자서명|온라인)")


class E03Analog:
    pattern_id = "E-03"
    pattern_name = "아날로그 잔재"
    category = "효율성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty():
                continue
            text = art.full_text
            has_digital = bool(_DIGITAL.search(text))
            if _STRONG.search(text):
                severity = "심각" if not has_digital else "경고"
                level = "강"
                # 키워드 종류에 따라 서브체크 분기
                if re.search(r"(서면으로|문서)", text):
                    sub = "E-03-a"
                elif re.search(r"(날인|인감)", text):
                    sub = "E-03-b"
                else:
                    sub = "E-03-c"
            elif _MID.search(text):
                severity = "주의" if not has_digital else "개선"
                level = "중"
                sub = "E-03-d"
            elif _WEAK.search(text) and not has_digital:
                severity = "개선"
                level = "약"
                sub = "E-03-a"
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
                        matched_text=f"아날로그({level})",
                        summary=(
                            f"{level}한 아날로그 잔재"
                            + (" + 전자 대안 부재" if not has_digital else "")
                        ),
                        fix_type="add_paragraph",
                        sub_check_id=sub,
                    ),
                )
            )
        return findings
