"""E-05 제재 공백 — 룰 후보 추출 (LLM 정밀판단은 engine/llm/judge.py).

설계서 §3.2 + 오탐 필터: "노력하여야" 등 훈시 의무 제외, 정책동사 제외.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_OBLIG = re.compile(r"하여야 한다")
_EXHORT = re.compile(r"(노력하여야|기본계획|시책|진흥|촉진|육성)")
_PENALTY = re.compile(r"(징역|벌금|과태료|과징금|영업정지|취소)")
_POLICY = re.compile(r"(지원|장려|진흥|촉진|육성|보조)")


class E05Sanction:
    pattern_id = "E-05"
    pattern_name = "제재 공백"
    category = "효율성"

    def scan(self, law: Law) -> list[Finding]:
        # 벌칙 조문 묶음 → 의무 조항이 벌칙 대상인지 확인
        penalty_text = "\n".join(a.full_text for a in law.articles if a.is_penalty())
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty():
                continue
            text = art.full_text
            if not _OBLIG.search(text):
                continue
            if _EXHORT.search(text) or _POLICY.search(text):
                continue  # 정책의무·훈시규정 제외
            # 벌칙 본문에 이 조문번호가 인용되었는지
            referenced = art.number in penalty_text
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
