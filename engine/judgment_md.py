"""LLM(제미나이/지피티) 판단용 Markdown 생성기.

엔진이 잡은 후보 findings + 법령 조문 전문을 한 파일로 묶어, LLM이
바로 입력으로 받아 정밀 판단할 수 있게 한다.

구조:
1. 메타 (법령명, 시행일, 등급, 후보 수)
2. LLM 지시 (TP/FP 판정 + 등급 재평가 + 권고 개선)
3. 카테고리별 요약 표
4. 조문 단위 섹션 (조문 전문 + 매칭 후보 인라인)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .schema import AnalysisResult, Article, Finding


def _format_finding(f: Finding) -> str:
    rec = f.recommendation or {}
    sub = rec.get("sub_check_id")
    template = rec.get("template")
    cases = rec.get("matched_cases") or []
    agencies = rec.get("related_agencies") or []

    lines: list[str] = []
    lines.append(f"#### 🔎 후보 — `{f.pattern_id}` {f.pattern_name} · **{f.severity}**")
    if sub:
        lines.append(f"- 서브체크: `{sub}`")
    lines.append(f"- 매칭: {f.matched_text or '—'}")
    lines.append(f"- 요약: {f.summary}")
    if f.fix_type:
        lines.append(f"- 수정 유형: `{f.fix_type}`")
    if template:
        lines.append(f"- 표준 권고: {template}")
    if rec.get("contextual"):
        lines.append(f"- Layer 3 (LLM) 권고: {rec['contextual']}")
    if agencies:
        lines.append(f"- 관련 기관: {', '.join(agencies)}")
    if rec.get("reference_note"):
        lines.append(f"- 근거: {rec['reference_note']}")
    if cases:
        lines.append("- 유사 사례:")
        for c in cases[:2]:
            url = c.get("url") or ""
            url_part = f" — <{url}>" if url else ""
            lines.append(
                f"  - {c['agency']} {c['date']} 「{c['target']}」 {c['sanction']}"
                f"{url_part}"
            )
    return "\n".join(lines)


def _format_article(art: Article, findings: list[Finding]) -> str:
    head = f"### {art.number}"
    if art.title:
        head += f" ({art.title})"
    body = art.full_text.strip()
    out = [head, "", "```", body, "```", ""]
    if findings:
        out.append(f"**🚩 엔진이 잡은 후보 — {len(findings)}건**")
        out.append("")
        for f in findings:
            out.append(_format_finding(f))
            out.append("")
    else:
        out.append("_엔진 후보 없음._")
        out.append("")
    return "\n".join(out)


_PROMPT_HEADER = """\
> **LLM 판단 요청** — 이 문서는 규정개선 분석 엔진이 자동 추출한 *후보* 결함 목록입니다.
> 룰 기반 1차 스캔 결과이므로 오탐(false positive)이 포함되어 있습니다.
> 다음을 검토해주세요:
>
> 1. 각 후보가 **진짜 결함**인지(TP) **오탐**인지(FP) 판정
> 2. 진짜 결함이면 **등급(심각/경고/주의/개선)** 재평가
> 3. **권고안의 적절성**과 개선 제안
> 4. 엔진이 **놓친 결함(미탐)**이 있는지 조문 전문을 직접 검토
>
> 한 조문에 여러 후보가 걸린 경우 `🔗 교차 패턴` 메타 finding이 동반됩니다.
> 등급 변경은 1단계 이내가 안전합니다(2단계↑는 사유 명시).
"""


def render(result: AnalysisResult) -> str:
    law = result.law
    by_article: dict[str, list[Finding]] = defaultdict(list)
    for f in result.findings:
        if f.is_false_positive:
            continue
        by_article[f.article_id].append(f)

    real = [f for f in result.findings if not f.is_false_positive]
    by_severity: dict[str, int] = defaultdict(int)
    by_pattern: dict[str, int] = defaultdict(int)
    by_category: dict[str, int] = defaultdict(int)
    for f in real:
        by_severity[f.severity] += 1
        by_pattern[f.pattern_id] += 1
        by_category[f.category] += 1

    out: list[str] = []
    out.append(f"# 「{law.name}」 LLM 판단용 자료")
    out.append("")
    out.append(_PROMPT_HEADER)
    out.append("")
    out.append("## 메타")
    out.append("")
    out.append(f"- 법령명: **{law.name}**")
    out.append(f"- 법령 구분: {law.type}")
    out.append(f"- 법령 카테고리: {law.law_category}")
    if law.effective_date:
        out.append(f"- 시행일: {law.effective_date}")
    if law.last_amended_date:
        out.append(f"- 공포·개정일: {law.last_amended_date}")
    out.append(f"- 총 조문: {law.total_articles}개")
    out.append(f"- 종합 등급: **{result.law_grade}** ({result.law_score}점)")
    out.append(f"- 후보 finding: {len(real)}건")
    out.append("")

    out.append("## 분석 요약")
    out.append("")
    out.append("### 등급 분포")
    out.append("")
    out.append("| 등급 | 건수 |")
    out.append("|------|------|")
    for sev in ("심각", "경고", "주의", "개선"):
        out.append(f"| {sev} | {by_severity.get(sev, 0)} |")
    out.append("")

    out.append("### 카테고리별 리스크")
    out.append("")
    out.append("| 카테고리 | 건수 | CRD |")
    out.append("|---------|------|-----|")
    for cat in ("구조", "공정성", "적법성", "거버넌스", "효율성"):
        cs = result.category_scores.get(cat)
        crd = cs.crd if cs else 0
        out.append(f"| {cat} | {by_category.get(cat, 0)} | {crd} |")
    out.append("")

    out.append("### 패턴별 후보")
    out.append("")
    out.append("| 패턴 | 건수 |")
    out.append("|------|------|")
    for pid in sorted(by_pattern):
        out.append(f"| {pid} | {by_pattern[pid]} |")
    out.append("")

    out.append("## 조문별 분석")
    out.append("")
    out.append("> 각 조문의 전문과 그 조문에 걸린 후보 finding을 함께 표시합니다.")
    out.append("> finding이 없는 조문은 _엔진 후보 없음_으로 표시되며, LLM이 직접 추가 결함을 식별할 수 있는 자료입니다.")
    out.append("")

    # 조문 순서대로 (law.articles)
    for art in law.articles:
        findings = by_article.get(art.article_id, [])
        out.append(_format_article(art, findings))

    # 법령 전체 단위 finding (article_id == "law_level")
    law_level_findings = [
        f for f in real if f.article_id == "law_level"
    ]
    if law_level_findings:
        out.append("## 법령 전체 단위 후보")
        out.append("")
        for f in law_level_findings:
            out.append(_format_finding(f))
            out.append("")

    out.append("---")
    out.append("")
    out.append(f"_엔진 v{result.engine_version} 자동 생성. 룰 20패턴 + Layer 1/2/3 권고 적용._")
    return "\n".join(out)
