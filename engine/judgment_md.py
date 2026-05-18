"""LLM(제미나이/지피티) 판단용 Markdown 생성기.

엔진이 잡은 후보 findings + 법령 조문 전문 + (있으면) 시행령·시행규칙
조문 전문을 한 파일로 묶어, LLM이 바로 입력으로 받아 정밀 판단할 수 있게 한다.

구조:
1. 메타 (법령명, 시행일, 등급, 후보 수, 위임 패밀리 표시)
2. LLM 지시 + 시스템 프롬프트
3. 등급·카테고리·패턴별 요약 표
4. 조문 단위 섹션 (법률 조문 + 후보 finding + 위임된 시행령 조문 매핑)
5. 부록: 시행령 전문 / 시행규칙 전문 (있으면)
6. 응답 JSON 스키마 재확인
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from .judgment_prompt import expected_schema_excerpt, header
from .schema import AnalysisResult, Article, Finding, Law


_DELEG_KEYS = re.compile(r"(대통령령|시행령|총리령|부령|시행규칙|고시)")


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


def _find_decree_matches(art: Article, decree: Law | None) -> list[Article]:
    """법률 조문이 위임한 사항에 대응할 가능성이 높은 시행령 조문 (±3조 휴리스틱)."""
    if decree is None or not _DELEG_KEYS.search(art.full_text):
        return []
    try:
        base = int(art.number_raw)
    except ValueError:
        return []
    matches: list[Article] = []
    for darticle in decree.articles:
        try:
            d_num = int(darticle.number_raw)
        except ValueError:
            continue
        if abs(d_num - base) <= 3:
            matches.append(darticle)
    return matches


def _format_subordinate_block(label: str, articles: list[Article]) -> list[str]:
    """위임 매핑 인라인 블록 (시행령/시행규칙 공통)."""
    out: list[str] = []
    out.append(f"**🔗 위임 → {label} 매핑 후보 ({len(articles)}건, ±3조 휴리스틱)**")
    out.append("")
    for a in articles[:3]:  # 최대 3개까지만 인라인
        title = f" ({a.title})" if a.title else ""
        out.append(f"<details><summary>{label} {a.number}{title}</summary>")
        out.append("")
        out.append("```")
        out.append(a.full_text.strip())
        out.append("```")
        out.append("</details>")
        out.append("")
    return out


def _format_article(
    art: Article,
    findings: list[Finding],
    *,
    decree: Law | None = None,
    rule: Law | None = None,
) -> str:
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

    # 시행령 위임 매핑
    decree_matches = _find_decree_matches(art, decree)
    if decree_matches:
        out.extend(_format_subordinate_block("시행령", decree_matches))

    # 시행규칙 위임 매핑 — 별표·서식 등 LLM이 위임 정합성 판단할 때 핵심 단서
    rule_matches = _find_decree_matches(art, rule)
    if rule_matches:
        out.extend(_format_subordinate_block("시행규칙", rule_matches))

    return "\n".join(out)


def render(
    result: AnalysisResult,
    *,
    decree: Law | None = None,
    rule: Law | None = None,
) -> str:
    """LLM 판단용 MD 렌더링.

    decree: 시행령 Law 객체 (위임 매핑에 사용)
    rule: 시행규칙 Law 객체 (부록에 포함)
    """
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
    out.append(header(law.name, len(real), law.total_articles))
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
    if decree is not None:
        out.append(f"- ✅ 시행령: **{decree.name}** ({decree.total_articles}조) — 부록 A 첨부")
    else:
        out.append("- ⚠ 시행령 없음 — S-02 위임검증은 본 법령만으로 한정")
    if rule is not None:
        out.append(f"- ✅ 시행규칙: **{rule.name}** ({rule.total_articles}조) — 부록 B 첨부")
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

    # 조문 순서대로 (law.articles) — 시행령·시행규칙 매핑 인라인 포함
    for art in law.articles:
        findings = by_article.get(art.article_id, [])
        out.append(_format_article(art, findings, decree=decree, rule=rule))

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

    # 부록 — 시행령 전문 (LLM이 S-02 위임 검증할 때 직접 확인 가능)
    if decree is not None:
        out.append("---")
        out.append("")
        out.append(f"## 📑 부록 A — 시행령 전문 「{decree.name}」")
        out.append("")
        out.append(f"> {decree.total_articles}개 조문. LLM은 위 본법 위임 조문의 정합성을 이 시행령에서 직접 확인하세요.")
        out.append("")
        for darticle in decree.articles:
            title = f" ({darticle.title})" if darticle.title else ""
            out.append(f"### [시행령] {darticle.number}{title}")
            out.append("")
            out.append("```")
            out.append(darticle.full_text.strip())
            out.append("```")
            out.append("")

    if rule is not None:
        out.append("---")
        out.append("")
        out.append(f"## 📑 부록 B — 시행규칙 전문 「{rule.name}」")
        out.append("")
        out.append(f"> {rule.total_articles}개 조문. 별표/서식 관련 사항은 이 시행규칙에 위임된 경우가 많습니다.")
        out.append("")
        for rarticle in rule.articles:
            title = f" ({rarticle.title})" if rarticle.title else ""
            out.append(f"### [시행규칙] {rarticle.number}{title}")
            out.append("")
            out.append("```")
            out.append(rarticle.full_text.strip())
            out.append("```")
            out.append("")

    out.append("---")
    out.append("")
    out.append(expected_schema_excerpt())
    out.append("")
    out.append(f"_엔진 v{result.engine_version} 자동 생성. 룰 20패턴 + Layer 1/2/3 권고 + 위임 매핑._")
    return "\n".join(out)
