"""뇌신경망 SLM 카테고리 분석 CLI.

법령(들)을 입력받아 카테고리별 진단을 JSON 으로 출력.

사용:
  python scripts/slm_analyze.py <법령명>           # 단일 법령 표 출력
  python scripts/slm_analyze.py <법령명> --json    # JSON 출력
  python scripts/slm_analyze.py --all              # 전체 corpus 요약
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.parser import parse_law
from engine.slm import analyze_law
from engine.slm.brain import CATEGORIES


def _load_law(law_name: str):
    md = Path(f"data/laws/raw/{law_name}/법률.md")
    if not md.exists():
        return None
    text = md.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    return parse_law(text, name=law_name)


def analyze_single(law_name: str, json_output: bool = False):
    law = _load_law(law_name)
    if law is None:
        print(f"법령 미존재: {law_name}", file=sys.stderr)
        return 1
    results = analyze_law(law)

    if json_output:
        out = {
            "law": law_name,
            "n_articles": len(law.articles),
            "categories": {
                cat: [d.to_dict() for d in results[cat][:20]]
                for cat in CATEGORIES
            },
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== {law_name} ({len(law.articles)} 조문) — 뇌신경망 SLM 진단 ===\n")
        for cat in CATEGORIES:
            diags = results[cat]
            if not diags:
                print(f"  {cat}: 정상")
                continue
            sev_counts: dict[str, int] = {}
            for d in diags:
                sev_counts[d.severity or "-"] = sev_counts.get(d.severity or "-", 0) + 1
            sev_str = " · ".join(f"{s}:{c}" for s, c in sorted(sev_counts.items(), key=lambda x: -x[1]))
            print(f"  {cat:<6}: {len(diags):>3}건 ({sev_str})")
            # 상위 3개 결함 조문
            top = sorted(diags, key=lambda x: -x.score)[:3]
            for d in top:
                sigs = ", ".join(f"{s}({w:+.2f})" for s, w in d.contributing_signals[:3])
                print(f"    [{d.severity}] {d.article_number} "
                      f"'{d.article_title[:25]}' score={d.score:.2f} → {sigs}")
    return 0


def analyze_all_summary():
    """전체 corpus 카테고리별 결함 분포 요약."""
    laws_dir = Path("data/laws/raw")
    if not laws_dir.exists():
        print("data/laws/raw 미존재", file=sys.stderr)
        return 1
    cat_dist: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    n_laws = 0
    for law_dir in laws_dir.iterdir():
        md = law_dir / "법률.md"
        if not md.exists():
            continue
        try:
            law = _load_law(law_dir.name)
        except Exception:
            continue
        if not law or not law.articles:
            continue
        n_laws += 1
        results = analyze_law(law)
        for cat in CATEGORIES:
            for d in results[cat]:
                if d.severity:
                    cat_dist[cat][d.severity] += 1
    print(f"\n=== 전체 {n_laws} 법령 SLM 카테고리 진단 분포 ===\n")
    for cat in CATEGORIES:
        dist = cat_dist[cat]
        total = sum(dist.values())
        avg = total / max(n_laws, 1)
        sev_str = " · ".join(f"{s}:{c}" for s, c in sorted(dist.items(), key=lambda x: -x[1]))
        print(f"  {cat:<6}: 총 {total:>5}건 (법령당 평균 {avg:.1f}건) — {sev_str}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="뇌신경망 SLM 카테고리 분석")
    parser.add_argument("law_name", nargs="?", help="법령명")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument("--all", action="store_true", help="전체 corpus 요약")
    args = parser.parse_args()

    if args.all:
        return analyze_all_summary()
    if not args.law_name:
        parser.print_help()
        return 1
    return analyze_single(args.law_name, json_output=args.json)


if __name__ == "__main__":
    sys.exit(main())
