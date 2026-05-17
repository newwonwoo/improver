"""F-05 자의적 재량 — 룰 단계만 (LLM 정밀판단은 다음 PR).

설계서 §3.2 F-05 + 오탐 필터: 수익적/협조 재량 제외, 침익적만 진짜.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_AGENCY_SUBJECT = re.compile(
    r"(장관|위원회|청장|시ㆍ도지사|시·도지사|시장|군수|구청장|공사|공단|위원장|원장)[^.]{0,60}(할 수 있다|할 수 있고)"
)
_VAGUE_TRIGGER = re.compile(r"(필요하다고 인정|필요한 경우|적절한|상당한)")
_BENEFIT_HINTS = ("지원", "보조", "융자", "장려", "촉진", "혜택", "감면")
_COOP_HINTS = ("협조", "요청할 수 있다")


def _is_benefit(text: str) -> bool:
    return any(h in text for h in _BENEFIT_HINTS)


def _is_cooperation(text: str) -> bool:
    return any(h in text for h in _COOP_HINTS)


class F05Discretion:
    pattern_id = "F-05"
    pattern_name = "자의적 재량"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty():
                continue
            text = art.full_text
            if not _AGENCY_SUBJECT.search(text):
                continue
            if not _VAGUE_TRIGGER.search(text):
                continue
            if _is_benefit(text) or _is_cooperation(text):
                continue  # FPC: 침익적만 진짜

            trigger_match = _VAGUE_TRIGGER.search(text)
            triggered = trigger_match.group(0) if trigger_match else ""
            severity = "심각"  # 행정청 + 포괄요건 + 기준 없음
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=triggered,
                        summary=f"자의적 재량: 행정청 + 포괄요건 ({triggered}) + 기준 없음",
                        fix_type="replace",
                        sub_check_id="F-05-b",
                    ),
                )
            )
        return findings
