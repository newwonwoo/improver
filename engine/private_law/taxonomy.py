"""사법(私法) 결함 taxonomy — 민·상법 정비 대상 (행정규제법과 별개 체계).

팀장 결정(2026-06-10): 'AskUserQuestion → 사법(私法) 확장 착수'.
행정규제법 결함(포괄위임·청문누락·과도재량)은 사법에 부적합. 사법 고유 결함을
실측 스캔(민법 1245조·상법 1257조)으로 도출하되, **정직한 한계**를 명시한다:

  naive 키워드 탐지는 오탐이 큼(실측):
   - '심신상실'(민§754)=현행 유효 용어(FP), '가족관계등록'(민§814)=호주제 *교정* 용어(FP).
  → 진짜 사문화·차별 표현은 **큐레이션된 사전 + SME 라벨**이 필요(대형 과제, 갈래가 인정).

따라서 본 착수는: 기계적으로 방어 가능하고 정밀 필터가 가능한 **P-DIGITAL(날인 강제
= 디지털 부적합)** 1종만 활성화하고, 나머지는 scaffold(설계만, 미활성)로 정직 분리.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrivateLawDefectType:
    code: str
    name: str
    rationale: str
    status: str          # active | scaffold_pending_sme
    fp_risk_note: str


# 사법 결함 taxonomy (착수 — active 1종, scaffold 4종)
PRIVATE_LAW_TAXONOMY: dict[str, PrivateLawDefectType] = {
    "P-DIGITAL": PrivateLawDefectType(
        code="P-DIGITAL",
        name="디지털 부적합(날인 강제)",
        rationale="기명날인·인감을 전자적 대체 없이 강제 — 전자문서·전자서명 시대 정비 대상.",
        status="active",
        fp_risk_note="'기명날인 또는 서명/전자서명' 병기는 이미 현대화 → 정밀 필터로 제외.",
    ),
    "P-ARCHAIC": PrivateLawDefectType(
        code="P-ARCHAIC",
        name="사문화·구시대 용어",
        rationale="한정치산·금치산 등 개정으로 대체됐으나 잔존하는 용어.",
        status="scaffold_pending_sme",
        fp_risk_note="'심신상실' 등 현행 유효 용어와 구분 불가 — 큐레이션 사전 필수(naive=FP).",
    ),
    "P-DISCRIM": PrivateLawDefectType(
        code="P-DISCRIM",
        name="차별·비대칭 표현",
        rationale="처/부 비대칭, 호주제 잔재 등 평등원칙 부합 정비.",
        status="scaffold_pending_sme",
        fp_risk_note="'가족관계등록'은 호주제 *교정* 결과 — 잔재와 교정을 SME가 구분해야 함.",
    ),
    "P-CITATION": PrivateLawDefectType(
        code="P-CITATION",
        name="인용 정합성(타법 폐지·개정)",
        rationale="인용 법령·조문이 폐지/개정되어 어긋남.",
        status="scaffold_pending_sme",
        fp_risk_note="기존 L-01~03 인용룰 재활용 가능하나 사법 인용 인덱스 별도 구축 필요.",
    ),
    "P-OBSOLETE-UNIT": PrivateLawDefectType(
        code="P-OBSOLETE-UNIT",
        name="구 도량형·화폐단위",
        rationale="구 화폐단위(圜 등)·도량형 잔재.",
        status="scaffold_pending_sme",
        fp_risk_note="일반 '원' 금액과 구분 필요 — naive 매칭 오탐 큼(실측 33건 대부분 정상).",
    ),
}


def active_types() -> list[str]:
    return [c for c, t in PRIVATE_LAW_TAXONOMY.items() if t.status == "active"]


def scaffold_types() -> list[str]:
    return [c for c, t in PRIVATE_LAW_TAXONOMY.items()
            if t.status == "scaffold_pending_sme"]
