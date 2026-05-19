"""S-03 모호 표현 (엔진 설계서 §3.2)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


# 고위험 모호 표현: 의무/권리를 좌우하는 재량적 판단기준
# 주의: "정당한 사유" 단독은 표준 입법 표현 → 제외
HIGH_RISK_VAGUE: list[str] = [
    "필요하다고 인정",
    "필요하다고 인정하는 때",
    "합리적인 이유",
    "합리적인 사유",
    "상당한 이유",
    "현저히 부당",
    "현저한 지장",
]

# 중위험 모호 표현: 처분·의무 조문에서 문제
MID_RISK_VAGUE: list[str] = [
    "상당한",
    "적절한",
    "적정한",
    "합리적인",
    "중대한",
    "현저한",
    "현저히",
    "필요한 경우",
]

# FPC: "그 밖에 ... 대통령령으로" 같은 위임 결합은 S-02에서 잡으므로 제외
_DELEG_TAIL = re.compile(r"(그 밖에|기타)[^.]{0,40}(대통령령|시행령|부령|총리령|시행규칙)")
# FP 필터: 처분·의무 컨텍스트가 없는 선언적 조문
_ENFORCEMENT_CONTEXT = re.compile(r"(취소|정지|처분|명령|제한|금지|의무|위반|과태료|과징금|벌금|징역)")
# FP 필터: 피동적 권리선언 (주의 사항 명시만)
_PASSIVE_DECL = re.compile(r"(보호받는다|보장된다|누릴 수 있다|존중되어야)")
# FP 필터: "정당한 사유 없이" / "정당한 이유 없이" — 거부·미이행 한정의 표준 입법 표현
_STD_REFUSAL_PHRASE = re.compile(r"정당한\s*(사유|이유)\s*없이")
# FP 필터: 형사·민사·행정심판 절차 도메인 — "상당한 이유" 등은 표준 용어
_LEGAL_PROCEDURE_DOMAIN = re.compile(
    r"(보호관찰|수사|체포|구속|압수|수색|감정|증거|기소|공소|항소|상고|재심"
    r"|행정심판|행정소송|민사소송|형사소송|재판|소송|심판|공판|심리)"
)


def _find_high_risk(text: str) -> list[str]:
    return [kw for kw in HIGH_RISK_VAGUE if kw in text]


def _find_mid_risk(text: str) -> list[str]:
    return [kw for kw in MID_RISK_VAGUE if kw in text]


class S03Vague:
    pattern_id = "S-03"
    pattern_name = "모호 표현"
    category = "구조"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_definition() or art.is_penalty() or art.is_purpose():
                continue
            text = art.full_text
            # 위임 결합 표현은 한 번씩만 제거
            cleaned = _DELEG_TAIL.sub("", text)
            # 표준 입법 표현 "정당한 사유 없이" 는 모호 평가 대상 아님
            cleaned = _STD_REFUSAL_PHRASE.sub("", cleaned)

            # 형사·민사·행정심판 절차 도메인: 표준 용어 다수 사용 → S-03 적용 제외
            if _LEGAL_PROCEDURE_DOMAIN.search(text):
                continue

            high_hits = _find_high_risk(cleaned)
            mid_hits = _find_mid_risk(cleaned)
            # 고위험 키워드: 처분·의무 컨텍스트 필요
            if high_hits and not _ENFORCEMENT_CONTEXT.search(cleaned):
                high_hits = []

            total_count = len(high_hits) + len(mid_hits)
            if total_count == 0:
                continue

            # 처분·의무 컨텍스트 없이 중위험만 있으면 기준 상향
            if not high_hits and not _ENFORCEMENT_CONTEXT.search(cleaned):
                if len(mid_hits) < 3:
                    continue

            is_oblig = art.is_obligation()
            has_high = len(high_hits) >= 1
            if has_high and is_oblig and len(high_hits) >= 2:
                severity = "심각"
            elif has_high and is_oblig:
                severity = "경고"
            elif has_high or (len(mid_hits) >= 3 and _ENFORCEMENT_CONTEXT.search(cleaned)):
                severity = "주의"
            elif len(mid_hits) >= 2 and _ENFORCEMENT_CONTEXT.search(cleaned):
                severity = "개선"
            else:
                continue

            all_hits = high_hits + mid_hits
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=", ".join(all_hits[:5]),
                        summary=f"모호 표현 {total_count}건: {', '.join(all_hits[:5])}",
                        fix_type="replace",
                        sub_check_id="S-03-a",
                    ),
                )
            )
        return findings
