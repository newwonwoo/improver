#!/usr/bin/env python3
"""엔진 강화 전/후 분석 결과 비교 리포트.

사용 예:
    python scripts/diff_report.py \\
        --before outputs/results --after outputs/results_with_llm \\
        --output outputs/before_after.json

또는 룰 갱신 후 재분석한 결과를 비교할 때도 사용 가능.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.diff_report import compare  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="강화 전/후 분석 비교")
    parser.add_argument("--before", required=True, help="강화 전 results 디렉토리")
    parser.add_argument("--after", required=True, help="강화 후 results 디렉토리")
    parser.add_argument("--output", default="outputs/before_after.json")
    args = parser.parse_args(argv)

    report = compare(Path(args.before), Path(args.after))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"공통 법령: {report['common_laws']}", file=sys.stderr)
    print(f"평균 점수 변화: {report['avg_score_delta']:+.2f}", file=sys.stderr)
    print(f"FP 마킹: {report['fp_count_before']} → {report['fp_count_after']} "
          f"({report['fp_increase']:+d})", file=sys.stderr)
    print(f"Layer 3 권고: {report['layer3_before']} → {report['layer3_after']}",
          file=sys.stderr)
    print(f"\n등급 전이 Top 5:", file=sys.stderr)
    for t, c in list(report["grade_transitions"].items())[:5]:
        print(f"  {t}: {c}건", file=sys.stderr)
    print(f"\nWrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
