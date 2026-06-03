#!/usr/bin/env python3
"""검토된 후보를 config 파일에 병합.

검토 단계:
    1. python scripts/extract_feedback.py
       → outputs/feedback/{case,template}_candidates.json 생성
    2. 사람이 각 후보의 "approved": true 필드를 추가 (편집기 또는 별도 도구)
    3. python scripts/apply_proposals.py --dry-run   # 변경 미리보기
       python scripts/apply_proposals.py             # 실제 적용 (백업 자동)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.proposal_applier import apply_case_candidates, apply_template_candidates  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="검토된 후보를 config에 병합")
    parser.add_argument("--feedback-dir", default="outputs/feedback")
    parser.add_argument("--cases-config", default="config/disciplinary_cases.json")
    parser.add_argument("--recs-config", default="config/recommendations.json")
    parser.add_argument("--overwrite-templates", action="store_true",
                        help="기존 (pattern, severity) 템플릿 덮어쓰기")
    parser.add_argument("--dry-run", action="store_true",
                        help="변경 사항만 출력 (config는 그대로)")
    parser.add_argument("--skip-cases", action="store_true")
    parser.add_argument("--skip-templates", action="store_true")
    args = parser.parse_args(argv)

    fb = Path(args.feedback_dir)
    summary: dict[str, dict[str, int]] = {}

    if not args.skip_cases:
        r = apply_case_candidates(
            candidates_path=fb / "case_candidates.json",
            target_path=Path(args.cases_config),
            dry_run=args.dry_run,
        )
        summary["cases"] = r.summary()
        if r.cases_added:
            print(f"[cases] 추가됨 ({len(r.cases_added)}):", file=sys.stderr)
            for c in r.cases_added[:10]:
                print(f"  + {c}", file=sys.stderr)
        if r.cases_skipped:
            print(f"[cases] 스킵 ({len(r.cases_skipped)})", file=sys.stderr)

    if not args.skip_templates:
        r = apply_template_candidates(
            candidates_path=fb / "template_candidates.json",
            target_path=Path(args.recs_config),
            overwrite=args.overwrite_templates,
            dry_run=args.dry_run,
        )
        summary["templates"] = r.summary()
        if r.templates_added:
            print(f"[templates] 추가 ({len(r.templates_added)}):", file=sys.stderr)
            for t in r.templates_added:
                print(f"  + {t}", file=sys.stderr)
        if r.templates_replaced:
            print(f"[templates] 교체 ({len(r.templates_replaced)})", file=sys.stderr)
        if r.templates_skipped:
            print(f"[templates] 스킵 ({len(r.templates_skipped)})", file=sys.stderr)

    if args.dry_run:
        print("\n(dry-run: 실제 파일은 변경되지 않았습니다.)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
