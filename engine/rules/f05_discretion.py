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
# 고위험 포괄기준: 직접 재량 판단기준이 되는 표현
_HIGH_VAGUE = re.compile(r"(필요하다고 인정|필요하다고 인정되는|정당한 사유 없이|상당한 이유 없이)")
# 중위험: 처분 맥락에서만 문제
_MID_VAGUE = re.compile(r"(필요한 경우|적절한|상당한)")
# 침익적 처분 맥락: 행정청이 이를 근거로 불이익 처분 가능
_ADVERSARIAL = re.compile(
    r"(취소|정지|제한|금지|명령|처분|부과|과징금|과태료|시정|삭제|철거"
    r"|환수|회수|폐쇄|명할\s*수\s*있다|해제할\s*수\s*있다|시정할\s*것을|지시할\s*수\s*있다)"
)
_BENEFIT_HINTS = ("지원", "보조", "융자", "장려", "촉진", "혜택", "감면", "설치", "구성")
_COOP_HINTS = ("협조", "요청할 수 있다", "협의할 수 있다", "요구할 수 있다")
_INTERNAL_ADMIN = re.compile(r"(감사계획|내부\s*규정|운영\s*규정|업무\s*지침|소속\s*직원|하급\s*기관)")


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
            if art.is_penalty() or art.is_definition() or art.is_purpose():
                continue
            text = art.full_text
            if not _AGENCY_SUBJECT.search(text):
                continue
            # 내부 행정 규정 (감사계획, 업무지침) — 시민 영향 없음
            if _INTERNAL_ADMIN.search(text):
                continue
            # 수익적/협조 재량은 FP
            if _is_benefit(text) or _is_cooperation(text):
                continue

            has_high = bool(_HIGH_VAGUE.search(text))
            has_mid = bool(_MID_VAGUE.search(text))
            has_adversarial = bool(_ADVERSARIAL.search(text))

            if has_high and has_adversarial:
                severity = "심각"
            elif has_high:
                # 포괄기준이 있어도 침익적 처분 없으면 경고로 낮춤
                severity = "경고"
            elif has_mid and has_adversarial:
                severity = "주의"
            else:
                continue  # 중위험 기준 + 침익적 처분 없음 = FP

            trigger_match = (_HIGH_VAGUE if has_high else _MID_VAGUE).search(text)
            triggered = trigger_match.group(0) if trigger_match else ""
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=triggered,
                        summary=f"자의적 재량: 행정청 + 포괄요건 ({triggered})"
                        + (" + 침익적 처분" if has_adversarial else ""),
                        fix_type="replace",
                        sub_check_id="F-05-b",
                    ),
                )
            )
        return findings
