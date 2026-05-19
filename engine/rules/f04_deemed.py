"""F-04 의사표시 의제 — 룰 후보 추출 (LLM 정밀판단은 engine/llm/judge.py)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import is_judicial_law, is_blacklisted
from .base import PatternResult, make_finding


_DEEMED = re.compile(r"(동의한 것으로 본다|승낙한 것으로 본다|이의가 없는 것으로 본다|갱신된 것으로 본다)")
_NOTICE = re.compile(r"(통지하여야|고지하여야|알려야)")
_PERIOD = re.compile(r"(\d+)\s*일")
_REVOKE = re.compile(r"(철회할 수 있다|취소할 수 있다)")

# SLM signal: 기관간 의견청취 의제는 행정 절차 (시민 권리 의제 X)
# Source: signal_candidates.json :: F-04 :: "지방의회 의견청취 의제(기관간 절차)"
_INTER_AGENCY_DEEMED = re.compile(
    r"(지방의회|관계\s*기관의?\s*장|위원회).{0,80}"
    r"(\d+일|\d+개월).{0,40}(이의가\s*없|의견.{0,10}없|의견\s*제시).{0,30}본다"
)
# SLM signal: 법률효과 의제 (의사표시 의제 X) — 의제의 본질 차이
# Source: signal_candidates.json :: F-04 :: "법률효과 의제 vs 의사표시 의제 구분"
_LEGAL_EFFECT_DEEMED = re.compile(
    r"(갱신|결정|고시|승계|성립|효력\s*발생|취득|상실|등록)된?\s*것으로\s*본다"
)
# 상사 낙부통지 (확립 법리)
_COMMERCIAL_NOTICE = re.compile(r"낙부.{0,20}통지")
# 적법 동의 의제: 고지·설명 + 철회·반대 의사 모두 명시
_PROPER_CONSENT_DEEMED = re.compile(
    r"(고지|설명|안내).{0,200}(철회|반대의?\s*의사|부동의)"
)


class F04Deemed:
    pattern_id = "F-04"
    pattern_name = "의사표시 의제"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "F-04"):
            return []
        # 사법·절차법령 — F-04 미적용 (verdict: 0 TP / 4 FP)
        if is_judicial_law(law.name):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if art.is_penalty():
                continue
            text = art.full_text
            if not _DEEMED.search(text):
                continue
            # SLM FP filters (signal_candidates :: F-04):
            # R5 examples:
            #   F-04-001@지방재정법류 (FP — 지방의회 의견청취)
            #   F-04-001@상법 (FP — 낙부통지 확립 법리)
            #   F-04-001@정보통신망법 (FP — 고지+철회 적법 동의)
            if _INTER_AGENCY_DEEMED.search(text):
                continue  # 기관간 절차 — 시민 의사표시 의제 X
            if _COMMERCIAL_NOTICE.search(text) and law.name == "상법":
                continue  # 상사 낙부통지 확립 법리
            if _PROPER_CONSENT_DEEMED.search(text):
                continue  # 고지+철회 명시된 적법 동의
            # 법률효과 의제 vs 의사표시 의제 — 의사표시 토큰이 없으면 다운그레이드
            is_volition_deemed = bool(re.search(
                r"(동의|승낙|취임|승인)한?\s*것으로\s*본다", text))
            if not is_volition_deemed and _LEGAL_EFFECT_DEEMED.search(text):
                continue  # 법률효과 의제 — F-04 영역 아님
            has_notice = bool(_NOTICE.search(text))
            period_match = _PERIOD.search(text)
            period = int(period_match.group(1)) if period_match else 0
            can_revoke = bool(_REVOKE.search(text))

            if not has_notice:
                severity = "심각"
            elif 0 < period < 14:
                severity = "심각"
            elif not can_revoke:
                severity = "경고"
            elif period == 0:
                severity = "주의"
            else:
                severity = "개선"

            idx += 1
            details = []
            if not has_notice:
                details.append("통지 부재")
            if 0 < period < 14:
                details.append(f"의제 기간 {period}일 (단기)")
            if not can_revoke:
                details.append("철회 불가")
            # F-04-b 통지, F-04-c 기간, F-04-d 철회
            if not has_notice:
                sub = "F-04-b"
            elif 0 < period < 14:
                sub = "F-04-c"
            else:
                sub = "F-04-d"
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=_DEEMED.search(text).group(0),
                        summary=f"의사표시 의제: {', '.join(details) or '기간/철회 점검 필요'}",
                        fix_type="add_paragraph",
                        sub_check_id=sub,
                    ),
                )
            )
        return findings
