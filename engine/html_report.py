"""정적 HTML 리포트 생성기 (Python 단독, web 빌드 의존 없음).

설계서 §3.3 + P-01~P-10 패턴 규칙을 적용한 단일 HTML 문서.
React 리포트는 web/이 별도 빌드가 필요하지만, 이 모듈은 그냥 .html 파일을 떨굼.
"""
from __future__ import annotations

from html import escape
from typing import Iterable

from .schema import AnalysisResult, Finding


_SEV_COLORS = {
    "심각": ("#fef2f2", "#fca5a5", "#991b1b"),
    "경고": ("#fffbeb", "#fde68a", "#92400e"),
    "주의": ("#eff6ff", "#bfdbfe", "#1e40af"),
    "개선": ("#f9fafb", "#d1d5db", "#4b5563"),
    "양호": ("#f0fdf4", "#bbf7d0", "#166534"),
}

_FIX_ICONS = {
    "delete": ("✂️", "문제 표현 삭제"),
    "replace": ("🔄", "대체 문구로 교체"),
    "proviso": ("📎", "단서 조항 추가"),
    "add_paragraph": ("➕", "새 항 신설"),
    "sub_legislation": ("📋", "시행령·고시로 보완"),
}

_CATEGORIES = ["구조", "공정성", "적법성", "거버넌스", "효율성"]


def _badge(severity: str) -> str:
    bg, bd, tx = _SEV_COLORS.get(severity, _SEV_COLORS["개선"])
    return (
        f'<span style="background:{bg};border:1px solid {bd};color:{tx};'
        f'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">{escape(severity)}</span>'
    )


def _fix_chip(fix_type: str | None) -> str:
    if not fix_type or fix_type not in _FIX_ICONS:
        return ""
    icon, label = _FIX_ICONS[fix_type]
    return f' <span style="font-size:11px;color:#4b5563">{icon} {label}</span>'


def _finding_card(f: Finding, same_count: int = 0) -> str:
    rec = f.recommendation or {}
    template = rec.get("contextual") or rec.get("template") or ""
    first_sentence = template
    # P-04: 위임 첫 문장 고정
    if f.pattern_id == "S-02" and template and not template.startswith("위임 자체"):
        first_sentence = (
            "위임 자체는 정상입니다. 문제는 시행령이 해당 사항을 빠뜨린 것입니다. " + template
        )
    cross_chip = (
        f' <span style="font-size:11px;color:#b45309">🔗 이 조문에 다른 문제도 {same_count - 1}건</span>'
        if same_count > 1 else ""
    )
    cases_html = ""
    matched_cases = rec.get("matched_cases") or []
    if matched_cases:
        cases_html = (
            '<div style="margin-top:8px;font-size:11px;color:#6b7280">📎 유사 사례: '
            + " · ".join(
                f'<a href="{escape(c.get("url") or "#")}" style="color:#2563eb;text-decoration:underline">'
                f'{escape(c["agency"])} {escape(c["date"])} {escape(c["target"])}</a>'
                for c in matched_cases[:2]
            )
            + "</div>"
        )
    agencies = rec.get("related_agencies") or []
    agency_chip = (
        f'<div style="font-size:11px;color:#6b7280;margin-top:4px">🏛 관련: {escape(", ".join(agencies))}</div>'
        if agencies else ""
    )
    ref_note = rec.get("reference_note")
    ref_chip = (
        f'<div style="font-size:11px;color:#6b7280;margin-top:4px">📐 근거: {escape(ref_note)}</div>'
        if ref_note else ""
    )

    return (
        '<div style="padding:10px;margin-bottom:8px;border:1px solid #e5e7eb;border-radius:6px;background:#fff">'
        + '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        + _badge(f.severity)
        + f'<strong>{escape(f.article_number)}</strong>'
        + f'<span style="font-size:11px;color:#6b7280">{escape(f.pattern_id)} {escape(f.pattern_name)}</span>'
        + _fix_chip(f.fix_type)
        + cross_chip
        + "</div>"
        + f'<div style="margin-top:8px;font-size:13px;line-height:1.6">{escape(f.summary)}</div>'
        + (
            f'<div style="margin-top:8px;font-size:12px;padding:8px;background:#f9fafb;'
            f'border-radius:4px;color:#374151">💡 {escape(first_sentence)}</div>'
            if first_sentence else ""
        )
        + ref_chip
        + agency_chip
        + cases_html
        + "</div>"
    )


def _checklist(findings: Iterable[Finding]) -> str:
    items = []
    for f in findings:
        if f.severity not in {"심각", "경고"} or f.is_false_positive:
            continue
        rec = f.recommendation or {}
        text = rec.get("contextual") or rec.get("template") or f.summary
        if text:
            items.append(text)
    if not items:
        return ""
    lis = "".join(
        f'<li style="padding:6px 0;font-size:13px;border-bottom:1px dashed #f3f4f6">☐ {escape(t)}</li>'
        for t in items
    )
    return (
        '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-top:16px">'
        '<div style="font-weight:700;margin-bottom:10px">☑ 사내규정 반영 체크리스트</div>'
        f'<ul style="list-style:none;padding:0;margin:0">{lis}</ul></div>'
    )


def _roadmap(findings: list[Finding]) -> str:
    buckets = {
        "즉시 (30일)": [f for f in findings if f.severity == "심각" and not f.is_false_positive],
        "단기 (90일)": [f for f in findings if f.severity == "경고" and not f.is_false_positive],
        "중기 (1년)": [f for f in findings if f.severity == "주의" and not f.is_false_positive],
    }
    out = []
    for label, items in buckets.items():
        agencies = set()
        for f in items:
            for a in (f.recommendation or {}).get("related_agencies") or []:
                agencies.add(a)
        agency_line = ", ".join(sorted(agencies)) or "법제처(체계정비), 감사원(후속점검)"
        rows = "".join(
            f'<div style="font-size:12px;padding:2px 0;color:#374151">· {escape(f.article_number)} '
            f'{escape(f.pattern_name)}: {escape(f.summary)}</div>'
            for f in items[:5]
        )
        more = f'<div style="font-size:11px;color:#9ca3af;margin-top:4px">… 외 {len(items) - 5}건</div>' if len(items) > 5 else ""
        out.append(
            '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-bottom:12px">'
            f'<div style="font-weight:700;margin-bottom:6px">⏱ {escape(label)} · {len(items)}건</div>'
            f'<div style="font-size:11px;color:#6b7280;margin-bottom:8px">🏛 관련: {escape(agency_line)}</div>'
            + rows + more + "</div>"
        )
    return "".join(out)


def _category_summary(result: AnalysisResult) -> str:
    findings = [f for f in result.findings if not f.is_false_positive]
    by_cat: dict[str, list[Finding]] = {c: [] for c in _CATEGORIES}
    for f in findings:
        by_cat.setdefault(f.category, []).append(f)
    blocks = []
    sev_order = ["양호", "개선", "주의", "경고", "심각"]
    for cat in _CATEGORIES:
        items = by_cat.get(cat, [])
        if not items:
            blocks.append(
                f'<details style="margin-bottom:6px"><summary style="padding:10px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;font-weight:700"> {escape(cat)} · 0건</summary></details>'
            )
            continue
        max_sev = max(items, key=lambda f: sev_order.index(f.severity)).severity
        bg, bd, tx = _SEV_COLORS[max_sev]
        rows = "".join(_finding_card(f) for f in items)
        blocks.append(
            f'<details style="margin-bottom:8px"><summary style="padding:10px;background:{bg};'
            f'border:1px solid {bd};color:{tx};border-radius:6px;font-weight:700;cursor:pointer">'
            f' {escape(cat)} · {len(items)}건 · 최고 {escape(max_sev)}</summary>'
            f'<div style="padding:12px;background:#fff;border:1px solid {bd};border-top:none;'
            f'border-radius:0 0 6px 6px">{rows}</div></details>'
        )
    return "".join(blocks)


def render(result: AnalysisResult) -> str:
    law = result.law
    findings = result.findings
    severe_n = sum(1 for f in findings if f.severity == "심각" and not f.is_false_positive)
    warn_n = sum(1 for f in findings if f.severity == "경고" and not f.is_false_positive)
    issue_articles = len({f.article_number for f in findings if not f.is_false_positive})

    head = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        f'<title>「{escape(law.name)}」 규정개선 진단 리포트</title>'
        '<style>body{margin:0;font-family:"Pretendard","Noto Sans KR",sans-serif;background:#f8f9fb;color:#1a1a2e}'
        'h2{font-size:14px;margin:24px 12px 8px}</style></head><body>'
    )

    # 표지 — P-07
    header = (
        '<header style="background:linear-gradient(135deg,#1e293b,#0f172a);color:#fff;padding:32px 24px">'
        '<div style="font-size:11px;color:#94a3b8;letter-spacing:1.5px">규정 진단 리포트</div>'
        f'<h1 style="font-size:22px;font-weight:800;margin:6px 0">「{escape(law.name)}」</h1>'
        f'<div style="font-size:12px;color:#94a3b8">{escape(law.type)} · 시행 {escape(law.effective_date or "-")} · '
        f'최종 개정 {escape(law.last_amended_date or "-")} · 총 {law.total_articles}개 조문</div>'
        '<div style="display:flex;align-items:center;gap:14px;margin-top:16px;padding:14px 16px;'
        'background:rgba(220,38,38,0.12);border:1px solid rgba(220,38,38,0.3);border-radius:10px">'
        f'<span style="font-size:36px;font-weight:900;color:#ef4444">{escape(result.law_grade)}</span>'
        f'<div><div style="font-size:13px;font-weight:600;color:#fca5a5">{result.law_score}점 · 발견 {len(findings)}건</div>'
        f'<div style="font-size:11px;color:#a8a29e;margin-top:2px">심각 {severe_n} · 경고 {warn_n}</div></div>'
        "</div></header>"
    )

    # P-01: 평서문 라벨 카드
    cards = (
        '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:16px">'
        f'<div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px">'
        f'<div style="font-size:11px;color:#6b7280">이슈가 있는 조문</div>'
        f'<div style="font-size:22px;font-weight:800;margin-top:6px">{issue_articles}개</div>'
        f'<div style="font-size:11px;color:#9ca3af;margin-top:4px">전체 {law.total_articles}개 중</div></div>'
        f'<div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px">'
        f'<div style="font-size:11px;color:#6b7280">총 발견 건수</div>'
        f'<div style="font-size:22px;font-weight:800;margin-top:6px">{len(findings)}건</div>'
        f'<div style="font-size:11px;color:#9ca3af;margin-top:4px">심각 {severe_n} · 경고 {warn_n}</div></div>'
        f'<div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px">'
        f'<div style="font-size:11px;color:#6b7280">종합 등급</div>'
        f'<div style="font-size:22px;font-weight:800;margin-top:6px">{escape(result.law_grade)}</div>'
        f'<div style="font-size:11px;color:#9ca3af;margin-top:4px">{result.law_score}점</div></div>'
        f'<div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px">'
        f'<div style="font-size:11px;color:#6b7280">분석 범위</div>'
        f'<div style="font-size:22px;font-weight:800;margin-top:6px">모든 항목 점검 완료</div>'
        f'<div style="font-size:11px;color:#9ca3af;margin-top:4px">20 패턴</div></div>'
        "</div>"
    )

    body = (
        '<div style="padding:0 16px 24px">'
        '<h2>카테고리별 진단</h2>'
        + _category_summary(result)
        + '<h2>개선 로드맵</h2>'
        + _roadmap(findings)
        + _checklist(findings)
        + '<div style="margin-top:24px;padding:12px;font-size:11px;color:#9ca3af;text-align:center">'
        f'엔진 v{escape(result.engine_version)} · 패턴 P-01~P-10 적용</div></div>'
    )

    return head + header + cards + body + "</body></html>"
