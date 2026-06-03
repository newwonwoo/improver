"""법령 분석 결과 → 사내규정 요구사항 목록.

설계서 §7.4: "결함 탐지(Phase 1)"를 뒤집으면 "요구사항(Phase 2)"이 된다.
예) G-04-b "위험평가 절차가 없다" → "위험평가 절차가 있어야 한다".

이 모듈은 AnalysisResult를 받아 RequirementType 별 키워드 명세를 만든다.
이후 사내규정 텍스트와 비교해 위법유형 5종을 판정한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from ..schema import AnalysisResult, Finding


class RequirementType(str, Enum):
    REQUIRE = "require"      # 법이 "만들라"고 한 것 → 사내규정에 있어야
    PERMIT = "permit"        # 법이 허용하는 범위 → 규정이 이보다 좁으면 ②축소
    FORBID = "forbid"        # 법이 금지하는 것 → 규정에 포함되면 ③초과
    MATCH = "match"          # 법이 정한 기준값 → 규정과 다르면 ④불일치
    UPDATE = "update"        # 현행법 참조 정보 → 규정이 옛 기준이면 ⑤미갱신


# 서브체크별 요구사항 템플릿 — 키워드 매칭으로 사내규정에서 검출할 항목
_SUBCHECK_TO_REQUIREMENT: dict[str, dict] = {
    # G-04 내부통제 5요소 — 사내규정에 5요소가 있어야 (require)
    "G-04-a": {
        "type": RequirementType.REQUIRE,
        "label": "내부통제기준·윤리강령",
        "keywords": ["내부통제기준", "윤리강령", "행동강령"],
    },
    "G-04-b": {
        "type": RequirementType.REQUIRE,
        "label": "위험평가 절차",
        "keywords": ["위험평가", "위험관리", "리스크"],
    },
    "G-04-c": {
        "type": RequirementType.REQUIRE,
        "label": "승인절차·직무분리",
        "keywords": ["승인절차", "결재", "직무분리"],
    },
    "G-04-d": {
        "type": RequirementType.REQUIRE,
        "label": "보고체계·정보소통",
        "keywords": ["보고체계", "정보공유"],
    },
    "G-04-e": {
        "type": RequirementType.REQUIRE,
        "label": "자체점검·모니터링",
        "keywords": ["자체점검", "모니터링", "내부감사"],
    },
    # G-03 감독 5요소
    "G-03-a": {"type": RequirementType.REQUIRE, "label": "감독 범위 명시",
               "keywords": ["감독 범위", "감독사항"]},
    "G-03-b": {"type": RequirementType.REQUIRE, "label": "감독 주기 명시",
               "keywords": ["분기", "반기", "매년"]},
    "G-03-d": {"type": RequirementType.REQUIRE, "label": "감독 결과 공개",
               "keywords": ["공시", "공개"]},
    "G-03-e": {"type": RequirementType.REQUIRE, "label": "시정명령권",
               "keywords": ["시정명령", "시정요구"]},
    # G-05 보고
    "G-05-a": {"type": RequirementType.REQUIRE, "label": "보고 주기",
               "keywords": ["분기 보고", "반기 보고", "매년 보고"]},
    "G-05-b": {"type": RequirementType.REQUIRE, "label": "보고 양식",
               "keywords": ["서식", "별지"]},
    # F-01 권리제한 — 구제수단은 require, 제한 자체는 forbid 초과
    "F-01-e": {"type": RequirementType.REQUIRE, "label": "이의신청·구제절차",
               "keywords": ["이의신청", "청문", "구제", "소명"]},
    # F-02 면책 — 전면면책 금지
    "F-02-a": {"type": RequirementType.FORBID, "label": "전면 면책 조항",
               "keywords": ["일체의 책임", "어떠한 책임", "모든 책임"]},
    # F-04 의제 — 통지 require
    "F-04-b": {"type": RequirementType.REQUIRE, "label": "사전 통지 의무",
               "keywords": ["통지", "고지"]},
    # F-05 재량 — 발동 요건 require
    "F-05-b": {"type": RequirementType.REQUIRE, "label": "재량 발동 요건 열거",
               "keywords": ["다음 각 호", "기준에 따라"]},
    # E-03 아날로그 — 전자 대안 require
    "E-03-a": {"type": RequirementType.REQUIRE, "label": "전자적 처리 허용",
               "keywords": ["전자문서", "전자적 방법"]},
    "E-03-b": {"type": RequirementType.FORBID, "label": "날인·인감 강제",
               "keywords": ["날인", "인감증명"]},
    # E-05 제재 — 의무에 대한 제재 require
    "E-05-a": {"type": RequirementType.REQUIRE, "label": "의무 위반 제재 조항",
               "keywords": ["과태료", "벌금", "징역", "영업정지"]},
    # L-01 인용 — 미갱신 (현행법 인용 필요)
    "L-01-b": {"type": RequirementType.UPDATE, "label": "현행 법령 인용",
               "keywords": []},
}


@dataclass
class Requirement:
    finding_id: str
    sub_check_id: str
    pattern_id: str
    article_number: str
    type: RequirementType
    label: str
    keywords: list[str] = field(default_factory=list)
    severity: str = "주의"

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "sub_check_id": self.sub_check_id,
            "pattern_id": self.pattern_id,
            "article_number": self.article_number,
            "type": self.type.value,
            "label": self.label,
            "keywords": list(self.keywords),
            "severity": self.severity,
        }


def extract_requirements(result: AnalysisResult) -> list[Requirement]:
    """AnalysisResult에서 사내규정 요구사항 목록을 추출."""
    requirements: list[Requirement] = []
    for f in result.findings:
        if f.is_false_positive:
            continue
        sub = (f.recommendation or {}).get("sub_check_id")
        if not sub:
            continue
        tmpl = _SUBCHECK_TO_REQUIREMENT.get(sub)
        if tmpl is None:
            continue
        requirements.append(
            Requirement(
                finding_id=f.finding_id,
                sub_check_id=sub,
                pattern_id=f.pattern_id,
                article_number=f.article_number,
                type=tmpl["type"],
                label=tmpl["label"],
                keywords=list(tmpl["keywords"]),
                severity=f.severity,
            )
        )
    return requirements
