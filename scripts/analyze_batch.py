#!/usr/bin/env python3
"""디렉토리 내 다수 법령을 일괄 분석.

사용법:
    python scripts/analyze_batch.py <법령_텍스트_디렉토리> --output-dir results/

각 .txt 파일을 분석해 동일 이름의 .json을 출력 디렉토리에 떨굼.
요약 통계(batch_summary.json)도 함께 생성: 법령별 점수·등급·발견 수.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import cases, cross_pattern, fpc, recommender, scorer  # noqa: E402
from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402


def _detect_category(name: str) -> str:
    if any(k in name for k in ("금융", "은행", "보험", "투자", "신용", "증권")):
        return "금융법"
    if any(k in name for k in ("공공기관", "공기업", "공단", "공사", "기금")):
        return "공공기관법"
    if any(k in name for k in ("민법", "상법", "계약")):
        return "민사법"
    if any(k in name for k in ("소송", "절차", "재판", "심판")):
        return "절차법"
    return "일반"


def _analyze_one(path_str: str, output_dir_str: str) -> dict:
    path = Path(path_str)
    output_dir = Path(output_dir_str)
    name = path.stem
    text = path.read_text(encoding="utf-8", errors="replace")
    law = parse_law(text, name=name, law_category=_detect_category(name))
    findings = fpc.correct(law, run_all(law))
    result = scorer.compute(law, findings)
    result = recommender.apply(result)
    result = cases.attach(result)
    result = cross_pattern.annotate(result)
    result = scorer.compute(law, result.findings)

    out_path = output_dir / f"{name}.json"
    out_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    severities = Counter(f.severity for f in result.findings if not f.is_false_positive)
    return {
        "name": name,
        "score": result.law_score,
        "grade": result.law_grade,
        "total_articles": law.total_articles,
        "total_findings": len(result.findings),
        "by_severity": dict(severities),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="법령 일괄 분석")
    parser.add_argument("root", help="법령 텍스트 디렉토리")
    parser.add_argument("--output-dir", default="results", help="결과 디렉토리")
    parser.add_argument("--workers", type=int, default=4,
                        help="동시 처리 프로세스 수")
    parser.add_argument("--summary", default="batch_summary.json",
                        help="요약 파일명 (output-dir 안에)")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"입력 디렉토리 없음: {root}", file=sys.stderr)
        return 1
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(root.glob("*.txt"))
    if not files:
        print(f"{root}에 .txt 파일이 없습니다", file=sys.stderr)
        return 1

    summaries: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(_analyze_one, str(p), str(output_dir)): p for p in files
        }
        for fut in as_completed(futures):
            try:
                summaries.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                print(f"실패 {futures[fut]}: {exc}", file=sys.stderr)

    summaries.sort(key=lambda s: -s["score"])
    grade_counter = Counter(s["grade"] for s in summaries)
    summary_payload = {
        "total_laws": len(summaries),
        "grade_distribution": dict(grade_counter),
        "top_20": summaries[:20],
        "all": summaries,
    }
    summary_path = output_dir / args.summary
    summary_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {summary_path} — {len(summaries)} laws", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
