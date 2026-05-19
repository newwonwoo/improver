"""F-04 의사표시 의제 — 룰 후보 추출 (LLM 정밀판단은 engine/llm/judge.py)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import is_judicial_law
from .base import PatternResult, make_finding


_DEEMED = re.compile(r"(동의한 것으로 본다|승낙한 것으로 본다|이의가 없는 것으로 본다|갱신된 것으로 본다)")
_NOTICE = re.compile(r"(통지하여야|고지하여야|알려야)")
_PERIOD = re.compile(r"(\d+)\s*일")
_REVOKE = re.compile(r"(철회할 수 있다|취소할 수 있다)")


class F04Deemed:
    pattern_id = "F-04"
    pattern_name = "의사표시 의제"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        # 사법·절차법령 — F-04 미적용 (verdict: 0 TP / 4 FP)
        if is_judicial_law(law.name):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty():
                continue
            text = art.full_text
            if not _DEEMED.search(text):
                continue
            has_notice = bool(_NOTICE.search(text))
            period_match = _PERIOD.search(text)
            period = int(period_match.group(1)) if period_match else 0
            can_revoke = bool(_REVOKE.search(text))

            if not has_notice:
                severity = "심각"
            elif 0 < period < 14:
                severity = "심각"
            elif not can_revoke:
                severity = "경고"
            elif period == 0:
                severity = "주의"
            else:
                severity = "개선"

            idx += 1
            details = []
            if not has_notice:
                details.append("통지 부재")
            if 0 < period < 14:
                details.append(f"의제 기간 {period}일 (단기)")
            if not can_revoke:
                details.append("철회 불가")
            # F-04-b 통지, F-04-c 기간, F-04-d 철회
            if not has_notice:
                sub = "F-04-b"
            elif 0 < period < 14:
                sub = "F-04-c"
            else:
                sub = "F-04-d"
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=_DEEMED.search(text).group(0),
                        summary=f"의사표시 의제: {', '.join(details) or '기간/철회 점검 필요'}",
                        fix_type="add_paragraph",
                        sub_check_id=sub,
                    ),
                )
            )
        return findings
