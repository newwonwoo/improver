"""L-06 기속처분 이행기한 부재 (BAI-04 · 행정절차법 제23조 기반).

행정절차법 §23: 행정청은 처분 기준을 공표해야 하며 처리기간을 명시해야 한다.
감사원 BAI-04 패턴: "하여야 한다" (기속처분) + 기한 미명시 → 행정재량 확대 위험.

TP 신호:
  - DISPOSITION·PROCEDURE 타입 + MUST modal + 기한(일수) 없음
  - "취소하여야 한다", "정지하여야 한다", "부과하여야 한다" + 기간 없음
  - 기속재량 처분 (허가취소·영업정지 필수요건 충족 시)에 처리기간 미명시

FP 필터:
  - 이미 "~일 이내" / "~개월 이내" 등 기한이 명시된 경우
  - "시행령으로 정한다" → 기한이 하위법령에 위임된 경우
  - 조직·권한·위임 조문 (기한 없이도 합법적)
  - 벌칙·정의·목적 조문
  - "노력하여야 한다" 류 훈시규정 (真 기속처분 아님)
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, Modal, is_blacklisted
from .base import PatternResult, make_finding

# 기속 처분 동사 — "하여야 한다" 형식
_BINDING = re.compile(
    r"(취소하여야|정지하여야|부과하여야|하여야|명하여야|통보하여야|통지하여야"
    r"|처분하여야|지정하여야|인정하여야|결정하여야|확인하여야)\s*한다"
)
# 훈시규정 — FP (강행규범 아님)
_EXHORTATORY = re.compile(
    r"(노력하여야|협력하여야|지원하여야|배려하여야|존중하여야|촉진하여야"
    r"|고려하여야|권장하여야|장려하여야)\s*한다"
)
# 기한 명시 신호 — FP
_HAS_DEADLINE = re.compile(
    r"(\d+\s*일\s*이내|\d+\s*개월\s*이내|\d+\s*년\s*이내"
    r"|즉시|지체\s*없이|기한\s*내에?|처리\s*기간|납부\s*기한|신청\s*기간)"
)
# 하위법령 위임 — FP (기한을 시행령에서 정하는 경우)
_DELEGATED_DEADLINE = re.compile(
    r"(대통령령|총리령|부령|시행령|시행규칙)으로\s*정하는?\s*(기한|기간|처리기간|처리절차)"
)
# 조직·권한 조문 — FP
_ORGANIZATIONAL = re.compile(
    r"(소속|감독|지휘|임명|임기|위원회|위원|사무|구성|조직|권한|직무|담당)"
)


def _is_fp_article(art: Article) -> bool:
    if art.is_definition() or art.is_purpose() or art.is_penalty():
        return True
    return False


class L06BindingDeadline:
    pattern_id = "L-06"
    pattern_name = "기속처분이행기한부재"
    category = "적법성"

    def scan(self, law: Law) -> list[Finding]:
        if is_blacklisted(law.name, "L-06"):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            d = decompose(art)
            # DISPOSITION 또는 PROCEDURE 타입만 대상
            if d.type not in (ArticleType.DISPOSITION, ArticleType.PROCEDURE, ArticleType.REPORTING):
                continue
            text = art.full_text

            # 기속처분 동사 패턴
            m = _BINDING.search(text)
            if not m:
                continue
            # 훈시규정 — FP
            if _EXHORTATORY.search(text):
                continue
            # 기한이 이미 명시된 경우 — FP
            if _HAS_DEADLINE.search(text):
                continue
            # 기한이 하위법령에 위임된 경우 — FP (개선으로 하향)
            delegated = bool(_DELEGATED_DEADLINE.search(text))
            # 조직/권한 조문 — FP
            if _ORGANIZATIONAL.search(text) and d.type != ArticleType.DISPOSITION:
                continue
            # MUST modal 확인 (R2 구조 신호)
            has_must = any(p.modal == Modal.MUST for p in d.paragraphs)
            # deadlines_days 가 없어야 진성 결함
            has_deadline_signal = bool(d.deadlines_days)
            if has_deadline_signal:
                continue

            if delegated:
                severity = "개선"
            elif has_must:
                severity = "경고"
            else:
                severity = "주의"

            idx += 1
            findings.append(make_finding(
                self, idx,
                PatternResult(
                    article=art,
                    severity=severity,
                    matched_text=m.group(0),
                    summary="기속처분 이행기한 미명시 — 처리기간 공표 필요"
                    + (" (위임으로 보완 가능)" if delegated else ""),
                    fix_type="add_paragraph",
                    sub_check_id="L-06-a",
                ),
            ))
        return findings
