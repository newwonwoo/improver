#!/usr/bin/env python3
"""LLM 응답에서 사례·권고 템플릿 후보 자동 추출.

P1: 컨텐츠 강화 자동화 — 사람이 검토할 후보 JSON만 생성, 자동 적용 안 함.

사용법:
    python scripts/extract_feedback.py
    # → outputs/feedback/case_candidates.json
    # → outputs/feedback/template_candidates.json

검토 후 적용 흐름:
    1. case_candidates.json 검토 → 유효 사례만 config/disciplinary_cases.json 에 병합
    2. template_candidates.json 검토 (diverges_from_current=true 우선) →
       유효한 것만 config/recommendations.json 에 반영
    3. 재분석 → 강화된 엔진 확인
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.feedback_extractor import export_proposals  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 응답에서 엔진 자산 후보 추출")
    parser.add_argument("--results-dir", default="outputs/results")
    parser.add_argument("--llm-dir", default="outputs/llm_responses")
    parser.add_argument("--output-dir", default="outputs/feedback")
    parser.add_argument("--current-recs", default="config/recommendations.json")
    args = parser.parse_args(argv)

    stats = export_proposals(
        results_dir=Path(args.results_dir),
        llm_dir=Path(args.llm_dir),
        current_recommendations_path=Path(args.current_recs),
        output_dir=Path(args.output_dir),
    )
    print(
        f"사례 후보: {stats['cases']}건, 템플릿 후보: {stats['templates']}건 "
        f"(현재와 다른 템플릿: {stats['diverging_templates']}건)",
        file=sys.stderr,
    )
    print(f"→ {args.output_dir}/case_candidates.json", file=sys.stderr)
    print(f"→ {args.output_dir}/template_candidates.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
