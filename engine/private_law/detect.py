"""사법 결함 탐지 — P-DIGITAL(날인 강제) active 룰 + 조문맞춤 권고.

정밀 필터(실측 근거): '기명날인 또는 서명/전자서명' 병기는 이미 전자대체 허용 →
정비 불요(FP). '기명날인하여야' 단독(서명 대체 없음)만 진성 디지털 부적합으로 발화.
LLM 0회. 행정규제법 엔진(run_all)과 분리 — 사법 입력에만 적용.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schema import Law

# 날인 강제 트리거
_SEAL_RX = re.compile(r"(기명날인|날인|인감|서명날인)")
# 이미 현대화(전자/서명 대체 허용) — 정밀 필터로 제외.
# '또는 서명' / '하거나 서명' / '날인하거나 서명' 등 서명 대체 병기를 모두 포착.
_MODERNIZED_RX = re.compile(r"(또는\s*서명|하거나\s*서명|또는\s*전자서명|하거나\s*전자서명|"
                           r"전자문서|전자적\s*방법|서명\s*또는|전자서명을\s*포함|날인\s*또는\s*서명)")
# 강제성(…하여야/…한다) — 임의규정과 구분
_MANDATORY_RX = re.compile(r"(기명날인|날인|서명날인)[^.。\n]{0,12}(하여야\s*한다|하여야|한다)")


@dataclass
class PrivateLawFinding:
    code: str
    article_number: str
    article_title: str
    matched_text: str
    rationale: str
    recommendation: str
    extract_method: str = "anchored"
    meta: dict = field(default_factory=dict)


def _digital_unfit(article) -> PrivateLawFinding | None:
    text = article.full_text or ""
    if not _SEAL_RX.search(text):
        return None
    if _MODERNIZED_RX.search(text):
        return None                       # 이미 전자/서명 대체 허용 → 정비 불요(FP 필터)
    m = _MANDATORY_RX.search(text)
    if not m:
        return None                       # 강제(하여야)만 — 임의규정 제외
    verbatim = m.group(0).strip()
    rec = (f"{article.number} 본문 「{verbatim}」 — 기명날인을 전자적 대체수단(전자서명·"
           f"전자문서) 없이 강제. 전자서명법·전자문서법과 정합하도록 '서명 또는 전자서명' "
           f"병기 등 디지털 대체 허용을 검토할 것.")
    return PrivateLawFinding(
        code="P-DIGITAL",
        article_number=article.number,
        article_title=article.title or "",
        matched_text=verbatim,
        rationale="날인 강제(전자 대체 없음) — 디지털 부적합.",
        recommendation=rec,
    )


def detect_private_law_defects(law: Law) -> list[PrivateLawFinding]:
    """사법 법령 → active 사법 결함 목록(현재 P-DIGITAL).

    scaffold 유형(P-ARCHAIC/DISCRIM/CITATION/OBSOLETE-UNIT)은 SME 큐레이션 대기로 미발화.
    """
    out: list[PrivateLawFinding] = []
    for art in law.articles:
        f = _digital_unfit(art)
        if f is not None:
            out.append(f)
    return out
