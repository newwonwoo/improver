#!/usr/bin/env python3
"""Phase 6 Agentic — SLM borderline 진단 / 그래프 엣지 검증 prompt 자동 생성.

두 모드:
  --mode edge   : Phase 4 그래프의 의심 엣지 검증 (cited_article / internal_ref)
  --mode verdict: SLM borderline 진단 (normalized 0.3~0.7) 의 TP/FP 검증

워크플로:
  1. `python scripts/slm_agentic_export.py --mode verdict --top 30 > /tmp/b.md`
  2. 사용자가 Claude.ai 에 prompt 복붙 → 응답 받음
  3. 응답 → `outputs/agentic_responses/<batch_id>.json` (수동 저장)
  4. (별도) import 스크립트가 verdict_dataset / law_graph 보정 반영

Prompt 형식:
  - YAML-ish header (bundle_id, mode, count)
  - 각 항목: 식별자 + 컨텍스트 (조문 본문 or 엣지 src/dst 인용 컨텍스트)
  - 응답 JSON schema 가이드 (필수 필드 명시)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.parser import parse_law  # noqa: E402
from engine.slm import (  # noqa: E402
    analyze_article,
    rank_diagnoses,
)
from engine.graph import LawGraph  # noqa: E402

_LAWS_DIR = Path("data/laws/raw")
_OUTPUT_DIR = Path("outputs/agentic_prompts")
_ARTICLE_BODY_MAX = 1200


def _clip(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + " …(생략)"


def _load_law(law_name: str):
    md = _LAWS_DIR / law_name / "법률.md"
    if not md.exists():
        return None
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return parse_law(text, name=law_name)
    except Exception:
        return None


def _find_article(law, number: str):
    for art in law.articles:
        if art.number == number:
            return art
    return None


# ============ Mode: verdict ============

@dataclass
class BorderlineCase:
    law: str
    article_number: str
    article_title: str
    category: str
    raw_score: float
    normalized_score: float
    sufficiency: float
    severity: str | None
    top_signals: list[tuple[str, float]]
    body: str


def _collect_borderline_cases(
    law_names: list[str],
    *,
    norm_lo: float = 0.40,
    norm_hi: float = 0.70,
    max_per_law: int = 5,
) -> list[BorderlineCase]:
    """SLM 진단에서 normalized_score 가 norm_lo~norm_hi 사이인 의심 케이스."""
    cases: list[BorderlineCase] = []
    for law_name in law_names:
        law = _load_law(law_name)
        if law is None:
            continue
        per_law_count = 0
        for art in law.articles:
            if art.is_definition() or art.is_purpose():
                continue
            diagnoses = analyze_article(art, law=law)
            ranked = rank_diagnoses(diagnoses)
            for cat, r in ranked.items():
                if norm_lo <= r.normalized_score <= norm_hi:
                    cases.append(BorderlineCase(
                        law=law_name,
                        article_number=art.number,
                        article_title=art.title or "",
                        category=cat,
                        raw_score=r.raw_score,
                        normalized_score=r.normalized_score,
                        sufficiency=r.sufficiency.overall,
                        severity=r.severity,
                        top_signals=r.contributing_signals[:5],
                        body=_clip(art.full_text, _ARTICLE_BODY_MAX),
                    ))
                    per_law_count += 1
                    if per_law_count >= max_per_law:
                        break
            if per_law_count >= max_per_law:
                break
    return cases


_VERDICT_HEADER = """\
당신은 한국 법제·규제 분석 전문가입니다. 법제처 입안길잡이, 감사원 내부통제,
공정위 약관규제법, 권익위 규제개혁, 금감원 검사제재 기준에 정통합니다.

규정개선 SLM 엔진이 아래 조문들을 5축 카테고리(구조/공정성/적법성/거버넌스/효율성)로
**borderline 진단**했습니다 (normalized_score 0.4~0.7 — 결함인지 정상인지 모호).

각 케이스에 대해 다음을 판정하세요:
1. **verdict**: TP (실제 결함) / FP (정상 입법, false positive) / BORDER (판단 보류)
2. **rationale**: 30자 이내 근거 (조문 인용 가능)
3. **suggested_severity** (TP 일 때만): 심각/경고/주의/개선

[FP 판정 사례]
- 정책의무·노력의무 (~노력하여야 한다, 진흥, 촉진, 육성)
- 위임이지만 이미 시행령에 구체화
- 정의·벌칙·목적 조문에서 잡힌 결함 (감쇄 부족)
- 협조요청·수익적 재량 (침익적 아님)

[출력 — 반드시 단일 JSON 객체만 응답. 마크다운·코드블록·설명 금지.]
{{
  "bundle_id": "{bundle_id}",
  "mode": "verdict",
  "results": [
    {{
      "case_id": "<case_id 그대로>",
      "verdict": "TP|FP|BORDER",
      "rationale": "...",
      "suggested_severity": "심각|경고|주의|개선|null"
    }}
  ]
}}

---
"""


def _render_verdict_prompt(cases: list[BorderlineCase], bundle_id: str) -> str:
    lines = [_VERDICT_HEADER.format(bundle_id=bundle_id)]
    for i, c in enumerate(cases, 1):
        cid = f"{c.law}#{c.article_number}#{c.category}"
        lines.append(f"## case_id: {cid}")
        lines.append("")
        lines.append(
            f"- 카테고리: **{c.category}** · normalized={c.normalized_score:.2f} · "
            f"raw={c.raw_score:.2f} · sufficiency={c.sufficiency:.2f} · 잠정 severity={c.severity or '없음'}"
        )
        sigs = ", ".join(f"`{n}`({w:+.2f})" for n, w in c.top_signals)
        lines.append(f"- 결정 신호: {sigs}")
        lines.append("")
        lines.append(f"**{c.article_number} {c.article_title}**")
        lines.append("")
        lines.append("```")
        lines.append(c.body)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


# ============ Mode: edge ============

def _collect_suspicious_edges(
    *,
    top: int,
    use_corpus_cache: bool = True,
    fallback_laws: list[str] | None = None,
) -> tuple[LawGraph | None, list]:
    """LawGraph cache 우선 사용. 없으면 fallback_laws 로 부분 그래프 빌드."""
    g = LawGraph.load() if use_corpus_cache else None
    if g is None and fallback_laws:
        g = LawGraph.empty()
        for ln in fallback_laws:
            law = _load_law(ln)
            if law is None:
                continue
            g._add_law_nodes(law)
        for ln in fallback_laws:
            law = _load_law(ln)
            if law is None:
                continue
            g._add_law_edges(law, only_internal=False)
    if g is None:
        return None, []
    return g, g.suspicious_edges(top=top)


_EDGE_HEADER = """\
당신은 한국 법제 전문가입니다. 아래는 SLM 엔진의 GraphRAG 그래프 (인용 관계) 에서
검증이 필요한 엣지 후보들입니다. 각 엣지 (src → dst) 가:

  - **VALID**  : 의미있는 위임/근거/참조 관계
  - **INVALID**: 단순 언급·중복·실제 무관계
  - **PARTIAL**: 부분적으로만 유효

판정 후 단일 JSON 으로 응답하세요.

[출력]
{{
  "bundle_id": "{bundle_id}",
  "mode": "edge",
  "results": [
    {{
      "edge_id": "<edge_id>",
      "verdict": "VALID|INVALID|PARTIAL",
      "rationale": "..."
    }}
  ]
}}

---
"""


def _render_edge_prompt(edges: list, bundle_id: str, graph: LawGraph) -> str:
    lines = [_EDGE_HEADER.format(bundle_id=bundle_id)]
    for i, (src, dst, kind) in enumerate(edges, 1):
        eid = f"{src[0]}#{src[1]}->{dst[0]}#{dst[1]}({kind})"
        lines.append(f"## edge_id: {eid}")
        lines.append("")
        lines.append(f"- 종류: **{kind}** · src=`{src}` · dst=`{dst}`")
        src_attr = graph.G.nodes[src]
        dst_attr = graph.G.nodes[dst]
        lines.append(f"- src 제목: {src_attr.get('title', '')}")
        lines.append(f"- dst 제목: {dst_attr.get('title', '')}")
        lines.append("")
    return "\n".join(lines)


# ============ main ============

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("verdict", "edge"), default="verdict")
    p.add_argument("--top", type=int, default=30, help="배치당 케이스 수")
    p.add_argument("--laws", nargs="*", help="대상 법령명 (기본: 1개 샘플)")
    p.add_argument("--norm-lo", type=float, default=0.40)
    p.add_argument("--norm-hi", type=float, default=0.70)
    p.add_argument("--output-dir", type=Path, default=_OUTPUT_DIR)
    p.add_argument("--stdout", action="store_true", help="파일 대신 stdout 출력")
    args = p.parse_args(argv)

    # 대상 법령
    laws = args.laws
    if not laws:
        # 기본 — verdict 모드는 작은 법령 몇 개 샘플
        if _LAWS_DIR.exists():
            laws = ["주택도시기금법"]
        else:
            laws = []

    bundle_id = f"{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if args.mode == "verdict":
        cases = _collect_borderline_cases(
            laws, norm_lo=args.norm_lo, norm_hi=args.norm_hi,
            max_per_law=max(args.top // max(len(laws), 1), 1),
        )
        cases = cases[: args.top]
        if not cases:
            print("(no borderline cases)", file=sys.stderr)
            return 1
        prompt = _render_verdict_prompt(cases, bundle_id)
        # category counter for visibility
        cats = Counter(c.category for c in cases)
        print(
            f"# bundle_id={bundle_id} cases={len(cases)} categories={dict(cats)}",
            file=sys.stderr,
        )
    else:  # edge
        graph, edges = _collect_suspicious_edges(top=args.top, fallback_laws=laws)
        if graph is None or not edges:
            print("(no edges available — Phase 4 graph not built)", file=sys.stderr)
            return 1
        prompt = _render_edge_prompt(edges, bundle_id, graph)
        print(f"# bundle_id={bundle_id} edges={len(edges)}", file=sys.stderr)

    if args.stdout:
        print(prompt)
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        out = args.output_dir / f"{bundle_id}.md"
        out.write_text(prompt, encoding="utf-8")
        print(f"wrote: {out}", file=sys.stderr)
        # JSON metadata sidecar
        meta = {
            "bundle_id": bundle_id,
            "mode": args.mode,
            "created_at": datetime.now().isoformat(),
            "count": (len(cases) if args.mode == "verdict" else len(edges)),
            "laws": laws,
        }
        (args.output_dir / f"{bundle_id}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
