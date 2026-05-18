#!/usr/bin/env python3
"""LLM 응답 수집 진척 추적.

사용법:
    python scripts/track_responses.py
    python scripts/track_responses.py --json   # JSON으로 stdout 출력

판단용 MD 디렉토리와 응답 디렉토리를 스캔해:
- 던졌으나 응답 못 받은 법령 (pending)
- 같은 법령에 응답이 여러 개 (duplicates)
- JSON 파싱 실패한 응답 (errored)

진척 인덱스를 outputs/llm_responses/_index.json 에 저장.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.response_tracker import scan, summarize, write_index  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 응답 수집 진척 추적")
    parser.add_argument("--judgments-dir", default="outputs/judgments")
    parser.add_argument("--responses-dir", default="outputs/llm_responses")
    parser.add_argument("--index-path", default=None,
                        help="기본: <responses-dir>/_index.json")
    parser.add_argument("--json", action="store_true", help="요약을 JSON으로 출력")
    args = parser.parse_args(argv)

    j_dir = Path(args.judgments_dir)
    r_dir = Path(args.responses_dir)
    r_dir.mkdir(parents=True, exist_ok=True)

    status = scan(judgments_dir=j_dir, responses_dir=r_dir)
    summary = summarize(status)

    index_path = Path(args.index_path) if args.index_path else r_dir / "_index.json"
    write_index(status, index_path)

    if args.json:
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    else:
        print(f"전체 법령: {summary['total_known']}", file=sys.stdout)
        print(f"  판단용 MD 있음: {summary['has_judgment_md']}", file=sys.stdout)
        print(f"  처리됨: {summary['processed']} "
              f"(진척 {summary['progress_rate'] * 100:.1f}%)", file=sys.stdout)
        print(f"  대기 중: {summary['pending_count']}", file=sys.stdout)
        if summary["pending_sample"]:
            for n in summary["pending_sample"][:5]:
                print(f"    - {n}", file=sys.stdout)
            if summary["pending_count"] > 5:
                print(f"    … 외 {summary['pending_count'] - 5}건", file=sys.stdout)
        if summary["duplicates_count"]:
            print(f"  중복 응답: {summary['duplicates_count']}", file=sys.stdout)
        if summary["errored_count"]:
            print(f"  ⚠ 파싱 실패: {summary['errored_count']}", file=sys.stdout)
        print(f"\n인덱스: {index_path}", file=sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
