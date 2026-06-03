#!/usr/bin/env python3
"""LLM 응답을 집계해 엔진 튜닝 제안을 생성.

워크플로:
    1. analyze_batch_sets.py        → outputs/results/*.json + outputs/judgments/*.md
    2. (수동) judgment MD를 LLM에 입력 → outputs/llm_responses/<법령명>.json 저장
    3. tune_engine.py               → outputs/tuning_proposals.json
    4. (수동) tuning_proposals.json 검토 후 config/patterns.json, recommendations.json 갱신

출력 (tuning_proposals.json):
    - per_pattern_stats: 패턴별 TP/FP/등급 변동 통계
    - fp_filter_proposals: FP 비율 ≥ 40% 패턴에 대한 필터 강화 제안
    - threshold_proposals: 등급 시프트가 큰 패턴에 대한 임계치 조정 제안
    - new_pattern_proposals: LLM이 X-NEW로 제안한 새 룰 후보
    - frequent_checklist_items: 표준 체크리스트로 승격 후보
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.learner import aggregate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="엔진 튜닝 제안 생성")
    parser.add_argument("--results-dir", default="outputs/results",
                        help="analyze_batch_sets.py가 생성한 결과 JSON 디렉토리")
    parser.add_argument("--llm-dir", default="outputs/llm_responses",
                        help="LLM 응답 JSON 디렉토리 (각 파일명 = 법령명.json)")
    parser.add_argument("--output", default="outputs/tuning_proposals.json",
                        help="튜닝 제안 출력 경로")
    args = parser.parse_args(argv)

    proposals = aggregate(
        results_dir=Path(args.results_dir),
        llm_responses_dir=Path(args.llm_dir),
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if "error" in proposals:
        print(f"⚠ {proposals['error']}", file=sys.stderr)
        return 1

    print(f"처리 법령: {proposals['laws_processed']}", file=sys.stderr)
    print(f"FP 필터 제안: {len(proposals['fp_filter_proposals'])}건", file=sys.stderr)
    print(f"임계치 제안: {len(proposals['threshold_proposals'])}건", file=sys.stderr)
    print(f"새 패턴 제안: {len(proposals['new_pattern_proposals'])}건", file=sys.stderr)
    print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
