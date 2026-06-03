"""G-02 승인·인허가 절차 (설계서 §3.2 G-02).

인허가를 직접 '신청받아 처리'하는 조문만 검사.
단순 인용·면제·의제 조문은 제외.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ActionKind
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
# FP 필터: 내부 임명·지정 (외부 인허가 아님)
# 소속 공무원·담당관·위원·이사 등의 지정은 G-02 영역 아님
_INTERNAL_DESIGNATION = re.compile(
    r"(소속\s*공무원|담당관을?\s*지정|위원장을?\s*지정|위원을?\s*지정"
    r"|이사를?\s*지정|간사를?\s*지정|직원\s*중에서|소속\s*직원|소속\s*기관)"
)
# FP 필터: 내부 행정 의사결정 (법원·심사위원회→장관 허가 등)
_INTERNAL_ADMIN_APPROVAL = re.compile(
    r"(심사위원회.{0,30}(허가를?\s*신청|결정한\s*경우)"
    r"|법무부장관에게.{0,20}허가를?\s*신청"
    r"|정관을?\s*변경.{0,15}인가"
    r"|정관의?\s*변경.{0,15}인가"
    r"|회계연도|예산안.{0,15}승인"
    r"|사업계획.{0,15}승인.{0,20}받아야)"
)
# FP 필터: 자격·결격·취소 사유 열거 조문 (인허가 처리가 아닌 사유 열거)
_DISQUALIFICATION_LIST = re.compile(
    r"(허가의?\s*기준|허가를?\s*하여서는\s*아니\s*된다"
    r"|허가를?\s*하지?\s*아니|결격\s*사유|취소\s*사유)"
)
# FP 필터: 데이터·정보 시스템 등록 (규제적 등록 아님)
_DATA_REGISTRATION = re.compile(
    r"(시스템에?\s*등록|정보를?\s*등록|자료를?\s*등록|결과를?\s*등록"
    r"|등록ㆍ관리|등록하여\s*관리|등록ㆍ공시|등록ㆍ공개)"
)
# FP 필터: 신청자/지원자 측의 신청 권리(허가 대상자가 아닌 수혜자)
_BENEFICIARY_APPLICATION = re.compile(
    r"(갱생보호\s*신청|급여를?\s*신청|혜택을?\s*신청|장학금을?\s*신청"
    r"|지원을?\s*신청|보조금을?\s*신청|기금을?\s*신청)"
)
# FP 필터: 자격요건 정의 조문 (인허가 처리 X)
_QUALIFICATION_DEFINITION = re.compile(
    r"(다음\s*각\s*호의?\s*어느\s*하나에?\s*해당하는\s*자만이?"
    r"|다음\s*각\s*호의?\s*어느\s*하나에?\s*해당하는\s*사람만이?)"
)
# Method B (Claude inline G-02_part01 검증)
# R5 examples:
#   G-02-047@강원특별법 (FP — 처분 취소조문)
#   G-02-011@공유수면법 (FP — 처분 취소조문)
#   G-02-042@공공주택특별법 (FP — 인허가의제)
#   G-02-001@공중협박목적특별법 (FP — 자금세탁 지정)
#   G-02-005@공직자윤리법 (FP — 재산등록 정의)
# 처분 취소 조문 (F-03 영역)
_G02_DISPOSITION_REVOCATION = re.compile(
    r"(인가|허가|면허|등록|지정)(\s*등?)?(의?)\s*취소"
    r"|^.{0,30}(취소하거나|취소하여야).{0,60}정지"
    r"|점용.{0,5}사용허가\s*등?의?\s*취소"
)
# 인허가의제 (의제 조문)
_G02_PERMIT_DEEMED_BODY = re.compile(
    r"(인[ㆍ·]?허가등을?\s*받은\s*것으로\s*본다|받은\s*것으로\s*보(며|고))"
)
# 자금세탁·제재 지정
_G02_SANCTION_DESIGNATION = re.compile(
    r"(자금세탁|대량살상무기|제재.{0,5}지정|금융거래등?\s*제한|특수관계자\s*지정)"
)
# 등록의무자·재산등록 정의
_G02_REGISTRATION_DEFINITION = re.compile(
    r"^(등록대상|등록의무자|등록할\s*재산|등록재산|용어의?\s*뜻)"
)
# FP 필터: 사법 절차 도메인 (법원·검사·사법경찰관)
_JUDICIAL_DOMAIN = re.compile(
    r"(사법경찰관|검사|법원|판사|공판|수사|체포|구속|압수|기소|공소"
    r"|상표등록출원|특허출원|심판청구|심결|보좌인)"
)
# FP 필터: 신청 철회·취하·정정·변경 조문 (인허가 처리 자체 아님)
_REVOCATION_PROC = re.compile(
    r"(신청을?\s*철회|신청을?\s*취하|신청을?\s*변경|신청을?\s*정정"
    r"|신청\s*철회|신청\s*취하|등록\s*취하|허가\s*취하)"
)
# FP 필터: 유효기간·갱신 조문 (인허가 발급이 아닌 기간 규정)
_VALIDITY_PERIOD = re.compile(
    r"(유효기간은?\s*\d+년|유효기간을?\s*\d+년|유효기간이?\s*\d+년"
    r"|기간을?\s*연장|기간이?\s*만료)"
)
# FP 필터: 공동 신청·복수 당사자 절차
_JOINT_APPLICATION = re.compile(
    r"(2인\s*이상이?\s*공동|공동으로\s*상표등록|공동으로\s*특허"
    r"|복수당사자|대표자를\s*선정)"
)


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
            # 내부 임명·지정 (담당관 지정 등)은 FP
            if _INTERNAL_DESIGNATION.search(text):
                continue
            # 내부 행정 의사결정 (심사위원회→장관 허가, 정관 변경 인가 등)은 FP
            if _INTERNAL_ADMIN_APPROVAL.search(text):
                continue
            # 결격·취소 사유 열거 조문 (실제 인허가 처리 X)
            if _DISQUALIFICATION_LIST.search(text):
                continue
            # 시스템·자료 등록 (규제적 등록 아님)
            if _DATA_REGISTRATION.search(text):
                continue
            # 수혜자 신청 (갱생보호·지원·보조금 신청 등)
            if _BENEFICIARY_APPLICATION.search(text):
                continue
            # 자격요건 정의 조문 ("…에 해당하는 자만이…")
            if _QUALIFICATION_DEFINITION.search(text):
                continue
            # Method B (Claude inline G-02_part01 검증) — article-level FP 필터:
            # 처분 취소·인허가의제·자금세탁지정·재산등록 정의는 G-02 적용 외.
            # (verdict 분포: 9 FP / 0 TP — 룰 광범위 발화 패턴 확인됨)
            # R5 examples: outputs/rule_verification_responses/G-02_part01.json
            if _G02_DISPOSITION_REVOCATION.search(art.title or ""):
                continue
            if _G02_PERMIT_DEEMED_BODY.search(text):
                continue
            if _G02_SANCTION_DESIGNATION.search(text):
                continue
            if _G02_REGISTRATION_DEFINITION.search((art.title or "").strip()):
                continue
            # 사법 절차 도메인 (법원·검사 등)
            if _JUDICIAL_DOMAIN.search(text):
                continue
            # 신청 철회·취하·변경 조문
            if _REVOCATION_PROC.search(text):
                continue
            # 유효기간·만료·연장 조문
            if _VALIDITY_PERIOD.search(text):
                continue
            # 공동 신청·복수 당사자 절차
            if _JOINT_APPLICATION.search(text):
                continue
            # 직접 처리 동사가 없으면 skip
            # R2 ActionKind: _PROCESSING_VERB 키워드 OR ActionKind.GRANT 구조 신호
            d = decompose(art)
            has_grant_action = ActionKind.GRANT in d.actions
            if not (_PROCESSING_VERB.search(text) or has_grant_action):
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
