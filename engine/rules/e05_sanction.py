"""E-05 제재 공백 — 룰 후보 추출 (LLM 정밀판단은 engine/llm/judge.py).

설계서 §3.2 + 오탐 필터: "노력하여야" 등 훈시 의무 제외, 정책동사 제외.
실질 의무(신고, 보고, 금지) 중 벌칙 무대응만 보고.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_OBLIG = re.compile(r"하여야 한다")
_EXHORT = re.compile(r"(노력하여야|기본계획|시책|진흥|촉진|육성|마련하여야|확보하여야)")
_PENALTY = re.compile(r"(징역|벌금|과태료|과징금|영업정지|취소)")
_POLICY = re.compile(r"(지원|장려|진흥|촉진|육성|보조|지급하여야|제공하여야)")
# FP: 절차적 의무 (보고·통지·공고 — 직접 제재 없어도 됨)
_PROCEDURAL = re.compile(
    r"(보고하여야|통지하여야|공고하여야|공시하여야|제출하여야|신고하여야"
    r"|게재하여야|공표하여야|비치하여야|교부하여야|송달하여야)"
)
# FP: 내부 절차 의무
_INTERNAL_PROC = re.compile(
    r"(회의를 개최하여야|출석하여야|서명하여야|날인하여야|기록하여야|보관하여야)"
)
# TP: 행위 금지 의무 (위반시 제재 필요)
_SUBSTANTIVE = re.compile(
    r"(등록하여야|허가를? 받아야|신청하여야|이행하여야|준수하여야|유지하여야"
    r"|확인하여야|설치하여야|갖추어야)"
)
# 벌칙 조문 내 일반 위반 조항 포괄 참조
_GENERAL_VIOLATION = re.compile(r"(이\s*법을?\s*위반한|이\s*법\s*또는|의무를\s*위반|규정을\s*위반)")


class E05Sanction:
    pattern_id = "E-05"
    pattern_name = "제재 공백"
    category = "효율성"

    def scan(self, law: Law) -> list[Finding]:
        # 벌칙 조문이 없는 법률 → 제재 공백 검사 의미 없음
        penalty_arts = [a for a in law.articles if a.is_penalty()]
        if not penalty_arts:
            return []
        penalty_text = "\n".join(a.full_text for a in penalty_arts)
        # 일반 포괄 위반 조항 있으면 E-05 스킵 (포괄적 참조로 대응됨)
        if _GENERAL_VIOLATION.search(penalty_text):
            return []

        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty() or art.is_definition() or art.is_purpose():
                continue
            if art.is_policy_obligation():
                continue
            text = art.full_text
            if not _OBLIG.search(text):
                continue
            if _EXHORT.search(text) or _POLICY.search(text):
                continue
            # 절차적·내부적 의무는 제재 공백이어도 무방
            if _PROCEDURAL.search(text) or _INTERNAL_PROC.search(text):
                continue
            # 실질 의무여야 함 (허가, 등록, 준수, 이행 등)
            if not _SUBSTANTIVE.search(text):
                continue
            # 벌칙 본문에 이 조문번호가 인용되었는지
            referenced = art.number in penalty_text or art.number_raw in penalty_text
            has_local_penalty = bool(_PENALTY.search(text))
            if referenced or has_local_penalty:
                continue
            severity = "경고"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text="하여야 한다",
                        summary=f"{art.number}의 의무에 대응하는 벌칙 미확인",
                        fix_type="add_paragraph",
                    ),
                )
            )
        return findings
