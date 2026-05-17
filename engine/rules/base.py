"""룰 패턴 공통 인터페이스."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..schema import Article, Finding, Law
from ..severity import score_of


@dataclass
class PatternResult:
    article: Article
    severity: str
    matched_text: str
    summary: str
    fix_type: str | None = None


class Rule(Protocol):
    pattern_id: str       # "S-03"
    pattern_name: str
    category: str         # 구조/공정성/적법성/거버넌스/효율성

    def scan(self, law: Law) -> list[Finding]: ...


def make_finding(rule: Rule, idx: int, result: PatternResult) -> Finding:
    finding_id = f"{rule.pattern_id}-{idx:03d}"
    return Finding(
        finding_id=finding_id,
        pattern_id=rule.pattern_id,
        pattern_name=rule.pattern_name,
        category=rule.category,
        article_id=result.article.article_id,
        article_number=result.article.number,
        matched_text=result.matched_text,
        severity=result.severity,
        severity_score=score_of(result.severity),
        summary=result.summary,
        fix_type=result.fix_type,
    )
