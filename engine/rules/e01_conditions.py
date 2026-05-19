"""E-01 조건 중첩 (엔진 설계서 §3.2).

조건 도입어("경우/때") + 접속사("및/또는/이고") 카운팅으로 단계 추정.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_CONDITION_LEAD = re.compile(r"(경우|때|요건)(?:에는|에)?")
_AND_OR = re.compile(r"(및|또는|이고|이며|하고|하며)")
_NESTED_HINT = re.compile(r"(에 해당하는 경우로서|충족하고|갖추어야 하며|모두 충족|다음 각 호의)")
# TP 부스트: 처분조 + 다단 조건
_DISPOSITION_HINT = re.compile(r"(취소|정지|명령|과징금|처분).{0,30}(경우|때)")
# FP 감쇄: 계획수립·진흥 등 정책 조문
_POLICY_HINT = re.compile(r"(기본계획|종합계획|시책|진흥|지원|육성|협력).{0,20}(수립|마련|추진|실시)")

# FP 필터: 순수 열거 조문 (단서·가목 없는 사항 열거)
_PURE_ENUM = re.compile(r"다음 각 호의? (사항|업무|사업|기준|방법|경우)")
# FP 필터: 수익적 지원 조문 (침익적 키워드 없이 지원/혜택만)
_BENEFIT_ONLY = re.compile(r"(지원할 수 있다|제공할 수 있다|보조할 수 있다|면제한다|보조금)")
_ADVERSARIAL = re.compile(r"(취소|정지|명령|제한|과징금|과태료|처벌|처분)")
# FP 필터: 위원회 심의 목록
_COMMITTEE_ENUM = re.compile(r"(위원회|심의회|평의원회).{0,30}(심의|자문|의결)")
# FP 필터: 단순 통보·신고 절차
_SIMPLE_PROCEDURE = re.compile(r"신고를 받은 날부터 \d+일 이내에 신고수리 여부를")
# TP 부스트: 재량/기속 혼재
_DISCRETION_MIXED = re.compile(r"취소할 수 있다")
_MANDATORY = re.compile(r"취소하여야 한다")


def _is_fp_article(art: Article) -> bool:
    """E-01 FP 필터."""
    if art.is_definition() or art.is_penalty() or art.is_purpose():
        return True
    if art.is_policy_obligation():
        return True
    text = art.full_text
    # 위원회 심의사항 열거
    if _COMMITTEE_ENUM.search(text) and _PURE_ENUM.search(text):
        return True
    # 단순 신고수리 절차 조문
    if _SIMPLE_PROCEDURE.search(text):
        return True
    # 수익적 지원 조문 — 침익적 제재 키워드 없으면 FP
    if _BENEFIT_ONLY.search(text) and not _ADVERSARIAL.search(text):
        return True
    return False


class E01Conditions:
    pattern_id = "E-01"
    pattern_name = "조건 중첩"
    category = "효율성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            text = art.full_text
            cond = len(_CONDITION_LEAD.findall(text))
            link = len(_AND_OR.findall(text))
            nested = len(_NESTED_HINT.findall(text))
            stages = nested + (cond // 2) + (link // 4)   # link weight 감소: //3→//4
            # TP 부스트: 재량/기속 혼재 (취소할 수 있다 + 취소하여야 한다)
            if _DISCRETION_MIXED.search(text) and _MANDATORY.search(text):
                stages += 2
            # TP 부스트: 처분 결과 조문의 조건 중첩은 더 위험
            if _DISPOSITION_HINT.search(text):
                stages += 1
            # FP 감쇄: 계획·진흥 조문의 조건은 덜 위험
            if _POLICY_HINT.search(text):
                stages = max(0, stages - 1)
            # FP 감쇄: 순수 열거(단서 없음, 가목 없음)
            if _PURE_ENUM.search(text) and "다만" not in text and "가." not in text and "가\\." not in text:
                stages = max(0, stages - 2)
            if stages < 5:
                continue
            if stages >= 9:
                severity = "심각"
            elif stages >= 7:
                severity = "경고"
            else:
                severity = "주의"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"조건 {stages}단계",
                        summary=f"조건 {stages}단계 중첩",
                        fix_type="replace",
                        sub_check_id="E-01-a",
                    ),
                )
            )
        return findings
