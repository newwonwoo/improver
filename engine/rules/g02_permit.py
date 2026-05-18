"""G-02 승인·인허가 절차 (설계서 §3.2 G-02)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_PROCS = ["인가", "허가", "승인", "신고", "등록", "면허", "지정", "인증"]
_DEADLINE = re.compile(r"(\d+\s*일 이내|기한)")
_DEEMED = re.compile(r"(한 것으로 본다|간주한다)")


class G02Permit:
    pattern_id = "G-02"
    pattern_name = "승인·인허가"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty():
                continue
            text = art.full_text
            present = [p for p in _PROCS if p in text]
            if not present:
                continue
            has_deadline = bool(_DEADLINE.search(text))
            has_deemed = bool(_DEEMED.search(text))

            # 중복 절차 (2종 이상)
            if len(present) >= 3:
                severity = "심각"
            elif not has_deadline:
                severity = "경고"
            elif not has_deemed:
                severity = "주의"
            else:
                continue

            idx += 1
            details = []
            if len(present) >= 3:
                details.append(f"중복 절차 {len(present)}종")
            if not has_deadline:
                details.append("처리 기한 부재")
            if not has_deemed:
                details.append("간주 규정 부재")
            # G-02-b 중복, G-02-c 처리기한, G-02-d 간주
            if len(present) >= 3:
                sub = "G-02-b"
            elif not has_deadline:
                sub = "G-02-c"
            else:
                sub = "G-02-d"
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=", ".join(present),
                        summary=", ".join(details),
                        fix_type="add_paragraph",
                        sub_check_id=sub,
                    ),
                )
            )
        return findings
