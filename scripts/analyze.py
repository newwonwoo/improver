#!/usr/bin/env python3
"""CLI 진입점: 법령 텍스트 → JSON 분석 결과.

사용법:
    python scripts/analyze.py <법령파일.txt> --name "법령명" [--output result.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 패키지 import 위해 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import fpc, recommender, scorer  # noqa: E402
from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402

try:
    from engine.llm import generate_recommendations, judge_findings  # noqa: E402
except ImportError:  # 의존성 없을 때 비활성화
    generate_recommendations = None  # type: ignore[assignment]
    judge_findings = None  # type: ignore[assignment]


def _detect_law_category(name: str) -> str:
    if any(k in name for k in ("금융", "은행", "보험", "투자", "신용", "증권", "여신")):
        return "금융법"
    if any(k in name for k in ("공공기관", "공기업", "공단", "공사", "기금")):
        return "공공기관법"
    if any(k in name for k in ("민법", "상법", "계약", "채권", "물권")):
        return "민사법"
    if any(k in name for k in ("소송", "절차", "재판", "심판")):
        return "절차법"
    return "일반"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="규정개선 분석기 CLI")
    parser.add_argument("input", help="법령 본문 텍스트 파일 경로")
    parser.add_argument("--name", required=True, help="법령명")
    parser.add_argument("--law-type", default="법률")
    parser.add_argument("--category", default=None, help="미지정 시 자동 판정")
    parser.add_argument("--output", default="-", help="결과 JSON 경로 (기본 stdout)")
    parser.add_argument("--use-llm", action="store_true",
                        help="LLM 정밀 판단 + Layer 3 권고안 (ANTHROPIC_API_KEY 필요)")
    args = parser.parse_args(argv)

    text = Path(args.input).read_text(encoding="utf-8")
    category = args.category or _detect_law_category(args.name)
    law = parse_law(text, name=args.name, law_type=args.law_type, law_category=category)

    findings = run_all(law)
    findings = fpc.correct(law, findings)
    result = scorer.compute(law, findings)
    result = recommender.apply(result)

    if args.use_llm and judge_findings and generate_recommendations:
        result = judge_findings(result)
        # 등급 변화 반영 후 점수 재계산
        result = scorer.compute(law, result.findings)
        result = recommender.apply(result)
        result = generate_recommendations(result)

    out_json = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    if args.output == "-":
        sys.stdout.write(out_json + "\n")
    else:
        Path(args.output).write_text(out_json, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
