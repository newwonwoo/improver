#!/usr/bin/env python3
"""
Phase 13 verdict 후보 127건 → Claude.ai batch markdown 내보내기

워크플로:
  1. python scripts/phase13_export_verdict_batches.py
     → outputs/phase13_verdict_batches/batch_NN.md (10~15건씩)
  2. 사용자: Claude.ai 에 batch 마크다운 복붙 → 응답 받음
  3. 응답을 outputs/phase13_verdict_responses/batch_NN.json 저장
  4. python scripts/phase13_import_verdict_responses.py
     → outputs/verification_dataset.jsonl 에 추가
  5. torch 재학습 → F1 회복 확인

batch 출력 형식:
  - 조문 본문 + moleg 해석례 본문
  - 우리 16개 규칙 중 발화된 것 (없으면 "발화 없음")
  - Claude.ai 가 답할 JSON 스키마 명시
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.parser import parse_law
from engine.slm.features import extract_features
from engine.reasoning import reason_over

CANDIDATES_FILE = ROOT / "outputs/phase13_verdict_candidates.jsonl"
MOLEG_DIR = ROOT / "outputs/rule_mining/sources/crawled/moleg_interp"
LAWS_DIR = ROOT / "data/laws/raw"
OUT_DIR = ROOT / "outputs/phase13_verdict_batches"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 10


def load_law_cached(name: str, cache: dict):
    if name in cache:
        return cache[name]
    md = LAWS_DIR / name / "법률.md"
    if not md.exists():
        cache[name] = None
        return None
    try:
        law = parse_law(md.read_text(encoding="utf-8"), name=name)
        cache[name] = law
        return law
    except Exception:
        cache[name] = None
        return None


def extract_moleg_body(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    # Strip header
    if "---" in text:
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    # Find 질의·회답·이유 sections only
    lines = text.split("\n")
    keep = []
    in_section = False
    for line in lines:
        if any(k in line for k in ["1. 질의", "2. 회답", "3. 이유", "4. 결론", "질의요지", "회답", "이유", "결론"]):
            in_section = True
        if in_section:
            keep.append(line)
        if len(keep) > 100:  # cap
            break
    body = "\n".join(keep).strip()
    # Length cap
    return body[:3000] if len(body) > 3000 else body


def render_batch(items: list, batch_idx: int) -> str:
    out = [
        f"# Phase 13 Verdict Batch #{batch_idx:02d} ({len(items)}건)",
        "",
        "## 배경",
        "법률 corpus 의 결함 진단 엔진(16개 추론 규칙)이 발화한 결과를, 법제처 법령해석례를 참고하여 TP/FP 라벨링.",
        "",
        "## 요청",
        "각 항목에 대해:",
        "1. 우리 규칙 발화가 정확한가? (TP/FP/BORDER)",
        "2. 해당 조문이 법령해석례의 쟁점과 관련 있는가?",
        "3. 추가로 발견한 결함 패턴이 있는가?",
        "",
        "## 응답 스키마 (JSON)",
        "```json",
        "{",
        '  "verdicts": [',
        '    {"id": 1, "verdict": "TP|FP|BORDER", "rule_id": "R-...", "reason": "..."},',
        "    ...",
        "  ]",
        "}",
        "```",
        "",
        "---",
        "",
    ]
    law_cache = {}
    for i, cand in enumerate(items, 1):
        law = load_law_cached(cand["law_name"], law_cache)
        if not law:
            out.append(f"### #{i} — {cand['law_name']} (corpus 없음, skip)")
            out.append("")
            continue
        # moleg body
        moleg_path = MOLEG_DIR / cand["file"]
        moleg_body = extract_moleg_body(moleg_path)
        # Match articles in the law that fire any rule
        fired_articles = []
        for art in law.articles[:30]:  # cap per law
            fv = extract_features(art)
            res = reason_over(fv)
            if res.steps:
                fired_articles.append((art, res))
        out.append(f"### #{i} — 법령: 「{cand['law_name']}」")
        out.append(f"**moleg 해석례**: {cand['title'][:150]}")
        out.append("")
        out.append(f"**moleg 본문 발췌**:")
        out.append("```")
        out.append(moleg_body[:1500])
        out.append("```")
        out.append("")
        out.append(f"**우리 진단엔진 발화 (이 법령의 상위 5개 결함 후보)**:")
        if not fired_articles:
            out.append("  (발화 없음)")
        else:
            for art, res in fired_articles[:5]:
                rules = ", ".join(s.rule_id for s in res.steps[:3])
                out.append(f"  - {art.number} {art.title or ''} → {rules}")
        out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out)


def main():
    candidates = []
    with open(CANDIDATES_FILE) as f:
        for line in f:
            candidates.append(json.loads(line))
    print(f"candidates: {len(candidates)}")

    # Group by moleg file to avoid duplicating law text
    seen = set()
    unique = []
    for c in candidates:
        key = (c["file"], c["law_name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    print(f"unique (file × law): {len(unique)}")

    # Batch
    n_batches = (len(unique) + BATCH_SIZE - 1) // BATCH_SIZE
    for b in range(n_batches):
        items = unique[b*BATCH_SIZE : (b+1)*BATCH_SIZE]
        md = render_batch(items, b + 1)
        out_path = OUT_DIR / f"batch_{b+1:02d}.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"  {out_path.relative_to(ROOT)} — {len(items)}건 ({len(md):,}자)")

    print(f"\n{n_batches} batches saved to {OUT_DIR.relative_to(ROOT)}")
    print("Next: Claude.ai 에 batch_01.md 부터 복붙 → 응답을 outputs/phase13_verdict_responses/batch_NN.json 으로 저장")


if __name__ == "__main__":
    main()
