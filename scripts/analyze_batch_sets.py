#!/usr/bin/env python3
"""법령 세트 디렉토리(법률+시행령+시행규칙) 일괄 분석 + judgment MD 생성.

기대 입력:
    <root>/<법령명>/{법률,시행령,시행규칙}.md

산출:
    <output-dir>/judgments/<법령명>.md       — LLM 판단용 MD (시행령 부록 포함)
    <output-dir>/results/<법령명>.json       — 분석 결과 JSON
    <output-dir>/batch_summary.json          — 등급 분포 + 인덱스

LLM 강화 워크플로:
    1. 본 스크립트로 모든 법령에 대해 judgment MD 생성
    2. 각 MD를 GPT/Gemini에 입력 → JSON 응답 받음
    3. import_judgment.py로 응답을 result에 반영
    4. learner.py(차후)로 LLM 응답을 모아 룰 임계치·FP 필터 튜닝
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import cases, cross_pattern, fpc, judgment_md, recommender, scorer  # noqa: E402
from engine.adapters import normalize_legalize_md  # noqa: E402
from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402


def _detect_category(name: str) -> str:
    if any(k in name for k in ("금융", "은행", "보험", "투자", "신용", "증권", "여신")):
        return "금융법"
    if any(k in name for k in ("공공기관", "공기업", "공단", "공사", "기금")):
        return "공공기관법"
    if any(k in name for k in ("민법", "상법", "계약", "채권", "물권")):
        return "민사법"
    if any(k in name for k in ("소송", "절차", "재판", "심판")):
        return "절차법"
    return "일반"


def _load_law(path: Path, *, name: str, law_type: str, law_category: str | None = None):
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("---"):
        text, meta = normalize_legalize_md(text)
    else:
        meta = {}
    category = law_category or _detect_category(name)
    return parse_law(
        text,
        name=name,
        law_type=meta.get("법령구분") or law_type,
        law_category=category,
        effective_date=meta.get("시행일자"),
        last_amended_date=meta.get("공포일자"),
    )


def _process_one(law_dir_str: str, output_dir_str: str) -> dict:
    law_dir = Path(law_dir_str)
    output_dir = Path(output_dir_str)
    name = law_dir.name
    law_file = law_dir / "법률.md"
    if not law_file.exists():
        return {"name": name, "status": "skip", "reason": "법률.md 없음"}

    try:
        law = _load_law(law_file, name=name, law_type="법률")
        if law.total_articles == 0:
            return {"name": name, "status": "skip", "reason": "조문 0개"}

        decree = None
        decree_file = law_dir / "시행령.md"
        if decree_file.exists():
            decree = _load_law(decree_file, name=f"{name} 시행령", law_type="대통령령",
                                law_category=law.law_category)

        rule = None
        rule_file = law_dir / "시행규칙.md"
        if rule_file.exists():
            rule = _load_law(rule_file, name=f"{name} 시행규칙", law_type="부령",
                              law_category=law.law_category)

        findings = fpc.correct(law, run_all(law))
        result = scorer.compute(law, findings)
        result = recommender.apply(result)
        result = cases.attach(result)
        result = cross_pattern.annotate(result)
        result = scorer.compute(law, result.findings)

        # judgment MD (시행령·시행규칙 부록 포함)
        md = judgment_md.render(result, decree=decree, rule=rule)
        md_path = output_dir / "judgments" / f"{name}.md"
        md_path.write_text(md, encoding="utf-8")

        # 결과 JSON
        json_path = output_dir / "results" / f"{name}.json"
        json_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        severities = Counter(f.severity for f in result.findings if not f.is_false_positive)
        return {
            "name": name,
            "status": "ok",
            "score": result.law_score,
            "grade": result.law_grade,
            "articles": law.total_articles,
            "findings": len(result.findings),
            "by_severity": dict(severities),
            "has_decree": decree is not None,
            "has_rule": rule is not None,
            "md_size": md_path.stat().st_size,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "status": "error",
            "reason": str(exc),
            "trace": traceback.format_exc()[-500:],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="법령 세트 일괄 분석")
    parser.add_argument("root", help="법령 세트 디렉토리 (예: data/laws/raw)")
    parser.add_argument("--output-dir", default="outputs", help="결과 디렉토리")
    parser.add_argument("--workers", type=int, default=4, help="동시 처리 프로세스 수")
    parser.add_argument("--limit", type=int, default=0, help="처리할 법령 수 (0=전체)")
    parser.add_argument("--filter", default=None, help="법령명에 포함된 키워드만 처리")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"입력 디렉토리 없음: {root}", file=sys.stderr)
        return 1
    output_dir = Path(args.output_dir)
    (output_dir / "judgments").mkdir(parents=True, exist_ok=True)
    (output_dir / "results").mkdir(parents=True, exist_ok=True)

    law_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    if args.filter:
        law_dirs = [p for p in law_dirs if args.filter in p.name]
    if args.limit:
        law_dirs = law_dirs[:args.limit]

    if not law_dirs:
        print(f"{root}에 처리 가능한 법령 디렉토리 없음", file=sys.stderr)
        return 1

    print(f"총 {len(law_dirs)}개 법령 분석 시작 (worker={args.workers})", file=sys.stderr)
    summaries: list[dict] = []
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_process_one, str(p), str(output_dir)): p for p in law_dirs}
        for fut in as_completed(futures):
            s = fut.result()
            summaries.append(s)
            done += 1
            if done % 100 == 0 or done == len(law_dirs):
                print(f"  진행 {done}/{len(law_dirs)}", file=sys.stderr)

    ok_summaries = [s for s in summaries if s.get("status") == "ok"]
    err_summaries = [s for s in summaries if s.get("status") == "error"]
    skip_summaries = [s for s in summaries if s.get("status") == "skip"]
    ok_summaries.sort(key=lambda s: -s["score"])

    grade_counter = Counter(s["grade"] for s in ok_summaries)
    pair_stats = Counter()
    for s in ok_summaries:
        key = ("법률" if not s["has_decree"] else "법률+시행령") + (
            "+시행규칙" if s["has_rule"] else ""
        )
        pair_stats[key] += 1

    payload = {
        "total_laws": len(law_dirs),
        "ok": len(ok_summaries),
        "skipped": len(skip_summaries),
        "errors": len(err_summaries),
        "grade_distribution": dict(grade_counter),
        "pair_distribution": dict(pair_stats),
        "top_20_severe": ok_summaries[:20],
        "errors_list": err_summaries[:50],
        "skipped_list": skip_summaries[:50],
        "all": ok_summaries,
    }
    summary_path = output_dir / "batch_summary.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"\n완료: OK={len(ok_summaries)} SKIP={len(skip_summaries)} "
        f"ERR={len(err_summaries)} → {summary_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
