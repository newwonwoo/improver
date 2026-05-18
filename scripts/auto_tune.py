#!/usr/bin/env python3
"""tuning_proposals.json의 명확한 항목을 patterns.json에 자동 적용.

사용법:
    python scripts/auto_tune.py --dry-run     # 변경 미리보기
    python scripts/auto_tune.py               # 적용 (백업 자동)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.auto_tuner import auto_tune  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 응답 집계 결과로 룰 자동 튜닝")
    parser.add_argument("--proposals", default="outputs/tuning_proposals.json")
    parser.add_argument("--patterns", default="config/patterns.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = auto_tune(
        proposals_path=Path(args.proposals),
        patterns_config_path=Path(args.patterns),
        dry_run=args.dry_run,
    )
    print(f"임계치 자동 조정: {len(report.threshold_changes)}건", file=sys.stderr)
    for c in report.threshold_changes:
        print(f"  {c['pattern_id']}: factor {c['adjust_factor']} (delta={c['delta']}, n={c['n']})",
              file=sys.stderr)
    print(f"FP 경고 플래그: {len(report.fp_filter_changes)}건", file=sys.stderr)
    print(f"수동 검토로 미룬 것: {len(report.skipped_for_review)}건", file=sys.stderr)
    if report.backup_path:
        print(f"백업: {report.backup_path}", file=sys.stderr)
    if args.dry_run:
        print("(dry-run)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
