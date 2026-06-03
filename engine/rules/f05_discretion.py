"""F-05 자의적 재량 — 룰 단계만 (LLM 정밀판단은 다음 PR).

설계서 §3.2 F-05 + 오탐 필터: 수익적/협조 재량 제외, 침익적만 진짜.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ActionKind
from .base import PatternResult, make_finding


_AGENCY_SUBJECT = re.compile(
    r"(장관|위원회|청장|시ㆍ도지사|시·도지사|시장|군수|구청장|공사|공단|위원장|원장)[^.]{0,60}(할 수 있다|할 수 있고)"
)
# 고위험 포괄기준: 직접 재량 판단기준이 되는 표현
# 주의: "정당한 사유 없이"·"상당한 이유 없이" 는 표준 입법 표현 → 제외
_HIGH_VAGUE = re.compile(r"(필요하다고 인정|필요하다고 인정되는)")
# 형사·민사·행정심판 절차 도메인 — "필요하다고 인정"이 표준 사법 재량
_LEGAL_PROCEDURE_DOMAIN = re.compile(
    r"(보호관찰|수사|체포|구속|압수|수색|감정|증거|기소|공소|항소|상고|재심"
    r"|행정심판|행정소송|민사소송|형사소송|재판|소송|심판|공판|심리)"
)
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
# Method B (Claude inline F-05_part01 검증) — 조사위·심의위 자체 절차 재량
# R5 examples:
#   F-05-002@이태원특별법 제16조 (의사의 공개) - 조사위 자체 운영
#   F-05-005@이태원특별법 제33조 (청문회 실시) - 조사위 청문절차
#   F-05-006@세월호특별법 제36조 (검증) - 위원회 자료 검증
_COMMITTEE_PROCEDURAL_DISCRETION = re.compile(
    r"(조사위원회|심의위원회|평가위원회|위원회).{0,80}(공개한다|의결|청문|검증)"
)
# 응급·재난·방역 공익 보호 행정
# R5 examples:
#   F-05-001@119구조ㆍ구급법 (응급의료)
#   F-05-001@가축전염병예방법 (방역)
_EMERGENCY_PROTECTION = re.compile(
    r"(응급의료|응급환자|구급|구조|재난|전염병|방역|위기관리|긴급)"
)
# 수익적 처분 명령 (휴직·보상·공로금 등)
# R5 examples:
#   F-05-001@세월호피해구제법 (휴직 명령)
#   F-05-001@비정규군공로자보상법 (공로금 지급)
_BENEFICIAL_ORDER = re.compile(
    r"(휴직을?\s*명할|보상금을?\s*지급|공로금을?\s*지급|급여를?\s*지급"
    r"|지원금을?\s*지급|장학금|연금)"
)


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
            # 형사·민사 절차 도메인 — "필요하다고 인정" 은 표준 사법 재량
            if _LEGAL_PROCEDURE_DOMAIN.search(text):
                continue
            # Method B: 조사위·심의위 자체 절차 재량 = FP
            if _COMMITTEE_PROCEDURAL_DISCRETION.search(text):
                continue
            # 응급·재난·방역 공익 보호 행정 = FP
            if _EMERGENCY_PROTECTION.search(text):
                continue
            # 수익적 처분 명령 (휴직·보상·공로금) = FP
            if _BENEFICIAL_ORDER.search(text):
                continue
            # 내부 행정 규정 (감사계획, 업무지침) — 시민 영향 없음
            if _INTERNAL_ADMIN.search(text):
                continue
            # 수익적/협조 재량은 FP
            if _is_benefit(text) or _is_cooperation(text):
                continue

            has_high = bool(_HIGH_VAGUE.search(text))
            has_mid = bool(_MID_VAGUE.search(text))
            # R2 ActionKind 보강: 키워드 패턴 OR 구조화 액션 (REVOKE|IMPOSE|RESTRICT)
            # Source: docs/ENGINE_PRINCIPLES.md R2 — 단어 매칭 대신 구조 신호
            d = decompose(art)
            adversarial_actions = d.actions & {
                ActionKind.REVOKE, ActionKind.IMPOSE, ActionKind.RESTRICT
            }
            has_adversarial = bool(_ADVERSARIAL.search(text)) or bool(adversarial_actions)

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
