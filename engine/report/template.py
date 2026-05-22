"""Markdown 리포트 템플릿 — f-string 기반 (Jinja2 불필요).

build_law_diagnosis: Law → LawDiagnosisOut (rerank + sufficiency 포함)
render_markdown    : LawDiagnosisOut → 마크다운
render_json        : LawDiagnosisOut → JSON
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ..schema import Law
from ..slm import (
    analyze_article,
    rank_diagnoses,
    diagnosis_to_standard,
    ArticleDiagnosisOut,
    CategorySummary,
    LawDiagnosisOut,
)

CATEGORIES = ("구조", "공정성", "적법성", "거버넌스", "효율성")
_SEVERITY_ORDER = ("심각", "경고", "주의", "개선")


def build_law_diagnosis(law: Law) -> LawDiagnosisOut:
    """Law 객체 → 표준 LawDiagnosisOut (Rerank + Sufficiency 포함)."""
    cat_diags: dict[str, list[ArticleDiagnosisOut]] = {c: [] for c in CATEGORIES}
    sev_dist: dict[str, dict[str, int]] = {
        c: {s: 0 for s in _SEVERITY_ORDER} for c in CATEGORIES
    }

    for art in law.articles:
        if art.is_definition() or art.is_purpose():
            continue
        diagnoses = analyze_article(art, law=law)
        ranked = rank_diagnoses(diagnoses)
        for cat in CATEGORIES:
            r = ranked[cat]
            if r.severity is None:
                continue
            out = diagnosis_to_standard(diagnoses[cat], source="slm", ranked=r)
            cat_diags[cat].append(out)
            sev_dist[cat][r.severity] = sev_dist[cat].get(r.severity, 0) + 1

    # 카테고리별 정렬: severity 우선, 그 다음 normalized_score 내림차순
    sev_rank = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
    for cat in CATEGORIES:
        cat_diags[cat].sort(
            key=lambda d: (sev_rank.get(d.severity or "", 99), -d.normalized_score)
        )

    categories: dict[str, CategorySummary] = {}
    for cat in CATEGORIES:
        diags = cat_diags[cat]
        if not diags:
            continue
        categories[cat] = CategorySummary(
            total_findings=len(diags),
            severity_distribution=sev_dist[cat],
            diagnoses=diags,
        )

    return LawDiagnosisOut(
        law_name=law.name,
        n_articles=len(law.articles),
        categories=categories,
        summary="",  # llm_summarize 가 채울 수 있음
    )


def render_json(diag: LawDiagnosisOut) -> str:
    return json.dumps(diag.to_dict(), ensure_ascii=False, indent=2)


def _format_signals(signals: list[Any], limit: int = 5) -> str:
    """SignalContribution list → 'name(+0.20), name2(-0.10)' 형식."""
    if not signals:
        return "(신호 없음)"
    parts = []
    for s in signals[:limit]:
        weight = s.weight if hasattr(s, "weight") else s.get("weight", 0)
        name = s.signal if hasattr(s, "signal") else s.get("signal", "?")
        parts.append(f"`{name}`({weight:+.2f})")
    return ", ".join(parts)


def _format_severity_dist(dist: dict[str, int]) -> str:
    parts = []
    for sev in _SEVERITY_ORDER:
        n = dist.get(sev, 0)
        if n > 0:
            parts.append(f"{sev} {n}")
    return ", ".join(parts) if parts else "—"


def _render_finding(d: ArticleDiagnosisOut) -> list[str]:
    lines = []
    sev = d.severity or "?"
    head = f"### [{sev}] {d.article_number} {d.article_title}".rstrip()
    lines.append(head)
    lines.append("")
    # 점수 + sufficiency
    norm = d.normalized_score
    raw = d.score
    if d.sufficiency:
        suff = d.sufficiency
        lines.append(
            f"- **점수**: normalized **{norm:.2f}** (raw {raw:.2f}) · "
            f"확신도 **{suff.overall:.2f}**"
        )
        lines.append(
            f"  - margin={suff.prediction_margin:.2f}, "
            f"coverage={suff.feature_coverage:.2f}, "
            f"balance={suff.signal_balance:.2f}, "
            f"graph_support={suff.graph_support:.2f}"
        )
    else:
        lines.append(f"- **점수**: {raw:.2f}")
    # 기여 신호
    lines.append(f"- **결정 신호**: {_format_signals(d.contributing_signals)}")
    if d.missing_signals:
        miss = ", ".join(f"`{s}`" for s in d.missing_signals[:3])
        lines.append(f"- **감쇄 신호**: {miss}")
    # 가독성
    if d.readability:
        r = d.readability
        lines.append(
            f"- **가독성**: 어절 {r.avg_words_per_sentence:.1f}/문장, "
            f"한자 {r.hanja_ratio*100:.1f}%, "
            f"점수 {r.readability_score:.2f}"
        )
    if d.suggestion:
        lines.append(f"- **권고**: {d.suggestion}")
    lines.append("")
    return lines


def render_markdown(diag: LawDiagnosisOut, *, max_per_category: int = 10) -> str:
    """LawDiagnosisOut → 마크다운 리포트 텍스트.

    max_per_category: 카테고리당 보여줄 결함 조문 수.
    """
    lines: list[str] = []
    # 제목 + 요약
    lines.append(f"# {diag.law_name} — 개선 진단 리포트")
    lines.append("")
    total_findings = sum(cs.total_findings for cs in diag.categories.values())
    lines.append("## 종합 요약")
    lines.append("")
    lines.append(
        f"- 분석 조문: **{diag.n_articles}**개 · "
        f"결함 발견: **{total_findings}**건"
    )
    cat_counts = ", ".join(
        f"{cat} {cs.total_findings}"
        for cat, cs in diag.categories.items()
    )
    if cat_counts:
        lines.append(f"- 카테고리별: {cat_counts}")
    if diag.summary:
        lines.append("")
        lines.append(diag.summary)
    lines.append("")

    # 카테고리별 결함
    for cat, cs in diag.categories.items():
        lines.append(f"## {cat}")
        lines.append("")
        lines.append(
            f"- 결함 **{cs.total_findings}**건 — {_format_severity_dist(cs.severity_distribution)}"
        )
        lines.append("")
        for d in cs.diagnoses[:max_per_category]:
            lines.extend(_render_finding(d))
        if len(cs.diagnoses) > max_per_category:
            remaining = len(cs.diagnoses) - max_per_category
            lines.append(f"_…외 {remaining}건 생략 (max_per_category={max_per_category})_")
            lines.append("")
    return "\n".join(lines)
