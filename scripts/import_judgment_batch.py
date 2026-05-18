#!/usr/bin/env python3
"""LLM JSON 응답 다수를 일괄로 분석 결과에 import.

기대 입력:
    --results-dir   엔진 분석 결과 JSON 디렉토리 (analyze_batch_sets.py 출력)
    --llm-dir       LLM 응답 JSON 디렉토리 (각 파일명 = 법령명.json)

각 매칭 쌍에 대해 import_judgment.py와 동일한 로직 적용.
결과는 --output-dir에 동일 파일명으로 저장.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.import_judgment import (  # noqa: E402
    _add_missed_findings,
    _apply_judgments,
    _result_from_dict,
)
from engine import scorer  # noqa: E402


def _process_pair(result_path_str: str, llm_path_str: str, out_path_str: str) -> dict:
    result_path = Path(result_path_str)
    llm_path = Path(llm_path_str)
    out_path = Path(out_path_str)

    analysis = json.loads(result_path.read_text(encoding="utf-8"))
    llm = json.loads(llm_path.read_text(encoding="utf-8"))
    result = _result_from_dict(analysis)

    stats = _apply_judgments(result, llm.get("judgments", []))
    added = _add_missed_findings(result, llm.get("missed_findings", []))
    result = scorer.compute(result.law, result.findings)
    payload = result.to_dict()
    payload["llm_review"] = {
        "judgments_applied": stats["applied"],
        "fp_marked": stats["fp_marked"],
        "severity_changed": stats["severity_changed"],
        "missing_finding_ids": stats["missing_ids"],
        "missed_findings_added": added,
        "checklist": llm.get("checklist", []),
        "overall_assessment": llm.get("overall_assessment", {}),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"name": result.law.name, "applied": stats["applied"], "fp": stats["fp_marked"],
            "missed_added": added, "new_grade": result.law_grade, "new_score": result.law_score}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 응답 일괄 import")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--llm-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    llm_dir = Path(args.llm_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs: list[tuple[Path, Path, Path]] = []
    for llm_file in llm_dir.glob("*.json"):
        result_file = results_dir / llm_file.name
        if result_file.exists():
            pairs.append((result_file, llm_file, output_dir / llm_file.name))

    if not pairs:
        print("매칭되는 result/llm 쌍이 없습니다.", file=sys.stderr)
        return 1

    print(f"{len(pairs)}쌍 처리 시작 (worker={args.workers})", file=sys.stderr)
    summaries: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = [
            ex.submit(_process_pair, str(r), str(l), str(o)) for r, l, o in pairs
        ]
        for fut in as_completed(futures):
            try:
                summaries.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                print(f"실패: {exc}", file=sys.stderr)

    summary_path = output_dir / "batch_import_summary.json"
    summary_path.write_text(
        json.dumps({"processed": len(summaries), "details": summaries},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"완료 {len(summaries)}건 → {summary_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
