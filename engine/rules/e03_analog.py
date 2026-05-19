"""E-03 아날로그 잔재 (전자 대안 부재 판별)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_STRONG = re.compile(r"(서면으로|날인|인감|대면하여|직접 출석)")
_MID = re.compile(r"(등기우편|내용증명|우편으로)")
_WEAK = re.compile(r"서면(?!으로)")  # 서면으로는 STRONG에서 처리; 단독 '서면'만
_DIGITAL = re.compile(r"(전자문서|전자적 방법|정보통신망|전자서명|온라인)")

# FP 필터: 법적 절차(법원/수사/청문회) — 서면/날인 요건은 사법적 정형 요건
_LEGAL_PROC = re.compile(
    r"(청문회|증인|감정인|소송|재판|심판|조정\s*조서|중재|기명\s*날인|서명\s*날인"
    r"|법원|검사|판사|변호사|동행명령|소환|출석\s*요구|조사위원회|수사|체포|구속|압수)"
)
# FP 필터: 문서 자체를 관리·보관·보호하는 조문 (기록보존, 비밀문서 등)
_DOC_MGMT = re.compile(
    r"(문서\s*보관|문서\s*관리|기록\s*보존|기밀\s*문서|비밀\s*문서|비밀\s*취급|문서함"
    r"|공문서\s*위조|전자\s*기록|정보\s*보호|개인\s*정보)"
)
# FP 필터: 정관·등기·설립 — 법인 설립 정형 서류는 아날로그 잔재가 아님
_CORP_DOC = re.compile(r"(정관|설립\s*등기|이사회|임원\s*명부|법인\s*등기)")
# FP 필터: 서면 심사·보고 (행정 내부 절차)
_INTERNAL_WRITTEN = re.compile(
    r"(서면\s*심사|서면\s*보고|서면\s*통보|서면\s*경고|서면\s*조사|서면\s*실태\s*조사"
    r"|서면으로.{0,20}보고하여야|서면으로.{0,20}통보하여야"
    r"|서면으로.{0,20}심의|서면으로.{0,20}의결|서면으로.{0,20}결의"
    r"|서면으로.{0,20}공고|서면으로.{0,20}고지|서면으로.{0,20}안내)"
)
# FP 필터: 위원회·이사회 의결 절차 (서면 결의는 회의 운영 방식)
_COMMITTEE_PROCEDURE = re.compile(
    r"(위원회.{0,40}서면|이사회.{0,40}서면|심의회.{0,40}서면"
    r"|위원의?\s*과반수|출석위원\s*과반수|의결정족수)"
)
# FP 필터: 등기·등록 등 부동산·법인 정형 절차의 서면 제출
_REGISTRY_DOC = re.compile(
    r"(등기관에게|등기소에|등기신청|법인등기|상업등기|부동산등기"
    r"|등기에\s*관한\s*법률|공정증서|인감증명)"
)
# TP 확인: 국민·사업자 신청·신고 맥락
_CITIZEN_FACING = re.compile(r"(신청하여야|신고하여야|제출하여야|청구하여야|요청하여야|등록하여야)")


def _is_fp(text: str) -> bool:
    """E-03 공통 FP 필터."""
    if _LEGAL_PROC.search(text):
        return True
    if _DOC_MGMT.search(text):
        return True
    if _CORP_DOC.search(text):
        return True
    if _INTERNAL_WRITTEN.search(text):
        return True
    if _COMMITTEE_PROCEDURE.search(text):
        return True
    if _REGISTRY_DOC.search(text):
        return True
    return False


class E03Analog:
    pattern_id = "E-03"
    pattern_name = "아날로그 잔재"
    category = "효율성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty() or art.is_purpose() or art.is_definition():
                continue
            text = art.full_text
            if _is_fp(text):
                continue
            has_digital = bool(_DIGITAL.search(text))
            if _STRONG.search(text):
                severity = "심각" if not has_digital else "경고"
                level = "강"
                if re.search(r"(날인|인감)", text):
                    sub = "E-03-b"
                elif re.search(r"(대면하여|직접 출석)", text):
                    sub = "E-03-c"
                else:
                    sub = "E-03-a"
            elif _MID.search(text):
                severity = "주의" if not has_digital else "개선"
                level = "중"
                sub = "E-03-d"
            elif _WEAK.search(text) and not has_digital and _CITIZEN_FACING.search(text):
                # 약 단계는 시민 신청 맥락이 있을 때만
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
