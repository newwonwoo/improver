"""교차 패턴 권고안 (핵심 설계서 §2.6).

동일 조문에 N개 이상 패턴이 동시에 걸렸을 때, 개별 권고와 별도로
"조문 재설계" 같은 구조적 권고를 추가 finding으로 부착한다.
"""
from __future__ import annotations

from collections import defaultdict

from .schema import AnalysisResult, Finding


# §2.6 임계치
_LINK_THRESHOLD = 2
_REDESIGN_THRESHOLD = 3
_RESTRUCTURE_THRESHOLD = 4

_REDESIGN_TEXT = (
    "해당 조문은 복합적 이슈를 가지고 있어 개별 수정보다 조문 재설계를 권고합니다."
)
_RESTRUCTURE_TEXT = (
    "해당 조문은 구조적 결함 상태입니다. "
    "폐지 후 목적별 분리 입법을 검토하시기 바랍니다."
)
_LAW_LEVEL_TEXT_FMT = (
    "패턴 {pattern}이 법령 전반에 {count}건 반복됩니다. "
    "개별 조문 수정이 아닌 법령 차원의 체계정비를 권고합니다."
)
_LAW_LEVEL_THRESHOLD = 5


def annotate(result: AnalysisResult) -> AnalysisResult:
    """결과에 교차 패턴 메타 finding을 추가."""
    by_article: dict[str, list[Finding]] = defaultdict(list)
    by_pattern: dict[str, list[Finding]] = defaultdict(list)
    for f in result.findings:
        if f.is_false_positive:
            continue
        by_article[f.article_id].append(f)
        by_pattern[f.pattern_id].append(f)

    extra: list[Finding] = []

    # 조문 단위 — 3패턴↑ / 4패턴↑
    for article_id, items in by_article.items():
        unique_patterns = {f.pattern_id for f in items}
        if len(unique_patterns) >= _LINK_THRESHOLD:
            # 모든 finding에 cross_pattern_count 메타 부착
            for f in items:
                rec = dict(f.recommendation or {})
                rec["cross_pattern_count"] = len(unique_patterns)
                f.recommendation = rec
        if len(unique_patterns) < _REDESIGN_THRESHOLD:
            continue
        first = items[0]
        text = _RESTRUCTURE_TEXT if len(unique_patterns) >= _RESTRUCTURE_THRESHOLD else _REDESIGN_TEXT
        extra.append(
            Finding(
                finding_id=f"X-CROSS-{article_id}",
                pattern_id="X-CROSS",
                pattern_name="교차 패턴",
                category="구조",
                article_id=article_id,
                article_number=first.article_number,
                matched_text=f"{len(unique_patterns)}개 패턴 동시",
                severity="경고",
                severity_score=7,
                summary=(
                    f"{first.article_number}에 {len(unique_patterns)}개 패턴 동시 적발 — "
                    + ", ".join(sorted(unique_patterns))
                ),
                fix_type="add_paragraph",
                recommendation={"template": text, "layer": 1, "cross_pattern": True},
            )
        )

    # 법령 단위 — 동일 패턴 5건↑
    for pattern_id, items in by_pattern.items():
        if pattern_id == "X-CROSS":
            continue
        if len(items) < _LAW_LEVEL_THRESHOLD:
            continue
        first = items[0]
        extra.append(
            Finding(
                finding_id=f"X-PATTERN-{pattern_id}",
                pattern_id="X-PATTERN",
                pattern_name=f"{pattern_id} 반복",
                category=first.category,
                article_id="law_level",
                article_number="법령 전체",
                matched_text=f"{pattern_id} {len(items)}건",
                severity="경고",
                severity_score=7,
                summary=_LAW_LEVEL_TEXT_FMT.format(pattern=pattern_id, count=len(items)),
                fix_type="sub_legislation",
                recommendation={"template": _LAW_LEVEL_TEXT_FMT.format(
                    pattern=pattern_id, count=len(items)), "layer": 1,
                    "cross_pattern": True},
            )
        )

    result.findings.extend(extra)
    return result
