"""공통 데이터 스키마 (엔진 설계서 §0).

파이프라인 전 구간이 공유하는 dataclass.  JSON 직렬화는 dataclasses.asdict 사용.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Item:
    item_id: str
    number: str | None
    text: str
    sub_items: list["Item"] = field(default_factory=list)


@dataclass
class Paragraph:
    para_id: str
    number: str | None
    text: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Article:
    article_id: str
    number: str             # "제10조" / "제10조의2"
    number_raw: str         # "10"
    is_inserted: bool = False
    insert_depth: int = 0
    title: str | None = None
    full_text: str = ""
    paragraphs: list[Paragraph] = field(default_factory=list)
    chapter: str | None = None

    def is_definition(self) -> bool:
        """FPC-02 용어정의 조문 판별."""
        if self.number_raw == "2" and self.title and ("정의" in self.title or "용어" in self.title):
            return True
        return "이 법에서 사용하는 용어의 뜻" in self.full_text

    def is_penalty(self) -> bool:
        """FPC-04 벌칙 조문 판별."""
        chap = self.chapter or ""
        if any(kw in chap for kw in ("벌칙", "과태료", "벌금", "징역")):
            return True
        return any(kw in self.full_text for kw in ("징역", "벌금", "과태료에 처한다"))

    def is_obligation(self) -> bool:
        """의무 조항(권리·의무 핵심 요건) 여부."""
        return any(kw in self.full_text for kw in ("하여야 한다", "하지 못한다", "금지한다"))


@dataclass
class Law:
    law_id: str
    name: str
    short_name: str | None = None
    type: str = "법률"
    law_category: str = "일반"           # 금융법/공공기관법/민사법/절차법/일반
    enacted_date: str | None = None
    last_amended_date: str | None = None
    effective_date: str | None = None
    articles: list[Article] = field(default_factory=list)

    @property
    def total_articles(self) -> int:
        return len(self.articles)


@dataclass
class Finding:
    finding_id: str
    pattern_id: str        # "S-03"
    pattern_name: str
    category: str          # 구조/공정성/적법성/거버넌스/효율성
    article_id: str
    article_number: str
    matched_text: str
    severity: str          # 심각/경고/주의/개선/양호
    severity_score: int
    summary: str
    detection_method: str = "rule"
    fix_type: str | None = None  # delete/replace/proviso/add_paragraph/sub_legislation
    recommendation: dict[str, Any] = field(default_factory=dict)
    is_false_positive: bool = False
    false_positive_reason: str | None = None


@dataclass
class ArticleScore:
    article_id: str
    article_number: str
    score: float
    grade: str             # Critical/Warning/Caution/Minor/Clean
    finding_count: int


@dataclass
class CategoryScore:
    crd: float             # category risk density
    weight: float
    finding_count: int


@dataclass
class AnalysisResult:
    law: Law
    findings: list[Finding]
    article_scores: list[ArticleScore]
    category_scores: dict[str, CategoryScore]
    law_score: float
    law_grade: str
    engine_version: str = "0.1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
