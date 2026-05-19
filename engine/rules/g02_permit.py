"""G-02 승인·인허가 절차 (설계서 §3.2 G-02).

인허가를 직접 '신청받아 처리'하는 조문만 검사.
단순 인용·면제·의제 조문은 제외.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_PROCS = ["인가", "허가", "승인", "신고", "등록", "면허", "지정", "인증"]
_DEADLINE = re.compile(r"(\d+\s*일 이내|기한)")
_DEEMED = re.compile(r"(한 것으로 본다|간주한다|수리한\s*것으로|허가한\s*것으로)")
# TP: 인허가 처리 주체와 신청/처리 행위가 명시된 경우
_PROCESSING_VERB = re.compile(
    r"(신청을?\s*받은|신청을?\s*하여야|신청할\s*수|심사하여야|검토하여야"
    r"|허가하여야|인가하여야|승인하여야|등록하여야|지정하여야"
    r"|신청서를|신청인에게|허가신청|인가신청|등록신청"
    r"|(인가|허가|승인|등록|면허)를?\s*(받아야|하여야|받고|받으며))"
)
# FP 필터: 인허가를 단순 면제/의제/준용하는 경우
_EXEMPT_OR_DEEMED = re.compile(
    r"(인[\s·ㆍ]?허가.{0,10}의제|적용하지\s*아니|면제한다|준용한다"
    r"|적용되지\s*아니|의제되는|의제한다)"
)
# FP 필터: 정의/벌칙/목적 등
_PROC_REFERENCE = re.compile(r"제\d+조에?\s*따른\s*(인가|허가|승인|등록|신고)")


class G02Permit:
    pattern_id = "G-02"
    pattern_name = "승인·인허가"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty() or art.is_definition() or art.is_purpose():
                continue
            text = art.full_text
            # 인허가 용어가 없으면 skip
            present = [p for p in _PROCS if p in text]
            if not present:
                continue
            # 면제·의제·준용 조문은 FP
            if _EXEMPT_OR_DEEMED.search(text):
                continue
            # 다른 조문 참조만 하는 경우 → FP
            if _PROC_REFERENCE.search(text) and not _PROCESSING_VERB.search(text):
                continue
            # 직접 처리 동사가 없으면 skip
            if not _PROCESSING_VERB.search(text):
                continue

            has_deadline = bool(_DEADLINE.search(text))
            has_deemed = bool(_DEEMED.search(text))

            # 중복 절차 (2종 이상 처리 행위)
            if len(present) >= 3 and not has_deadline:
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
                        matched_text=", ".join(present[:4]),
                        summary=", ".join(details),
                        fix_type="add_paragraph",
                        sub_check_id=sub,
                    ),
                )
            )
        return findings
