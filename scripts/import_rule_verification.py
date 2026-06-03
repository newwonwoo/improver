#!/usr/bin/env python3
"""Stage A 응답 통합 — verification_dataset.jsonl + 신호 후보 모음.

docs/design/engine_reinforcement_strategy.md Stage A.5.5 의 마지막 단계.

입력:
    outputs/rule_verification/_index.json — 생성된 sub-bundle 목록
    outputs/rule_verification_responses/<bundle_id>.json — LLM 응답들

출력:
    outputs/verification_dataset.jsonl — verdict 단위 한 줄씩
    outputs/signal_candidates.json — 룰별로 모은 new_signals / missed_patterns
    outputs/verification_progress.md — 진척 보고서 (어느 번들이 누락/오류인지)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


_VERDICT_VALUES = {"TP", "FP", "BORDER"}


def _strip_codeblock(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _validate(bundle_id: str, expected_rule: str, data: dict) -> list[str]:
    errs: list[str] = []
    if data.get("bundle_id") != bundle_id:
        errs.append(f"bundle_id 불일치: 응답={data.get('bundle_id')!r}")
    if data.get("rule_id") != expected_rule:
        errs.append(f"rule_id 불일치: 응답={data.get('rule_id')!r}")
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, list):
        errs.append("verdicts 누락 또는 리스트 아님")
    else:
        for i, v in enumerate(verdicts[:3]):  # 앞 3개만 spot
            if not isinstance(v, dict):
                errs.append(f"verdict[{i}] not dict")
                continue
            if "fid" not in v:
                errs.append(f"verdict[{i}] fid 없음")
            if v.get("v") not in _VERDICT_VALUES:
                errs.append(f"verdict[{i}].v={v.get('v')!r} (TP/FP/BORDER 아님)")
    for key in ("new_signals", "missed_patterns"):
        items = data.get(key, [])
        if items is not None and not isinstance(items, list):
            errs.append(f"{key} 는 리스트여야 함")
    return errs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage A 응답 통합")
    parser.add_argument("--bundles-dir", default="outputs/rule_verification")
    parser.add_argument(
        "--responses-dir", default="outputs/rule_verification_responses"
    )
    parser.add_argument(
        "--dataset", default="outputs/verification_dataset.jsonl",
        help="verdict 단위 jsonl 출력 — Stage B 입력",
    )
    parser.add_argument(
        "--signals", default="outputs/signal_candidates.json",
        help="룰별 new_signals + missed_patterns 모음",
    )
    parser.add_argument(
        "--progress", default="outputs/verification_progress.md",
        help="진척 보고서 — 누락/오류 추적",
    )
    args = parser.parse_args(argv)

    bundles_dir = Path(args.bundles_dir)
    responses_dir = Path(args.responses_dir)
    responses_dir.mkdir(parents=True, exist_ok=True)

    index_path = bundles_dir / "_index.json"
    if not index_path.exists():
        print(
            f"번들 인덱스 없음: {index_path}. 먼저 bundle_rule_verification.py 실행.",
            file=sys.stderr,
        )
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    bundles = index["bundles"]

    verdict_rows: list[dict] = []
    signals_by_rule: dict[str, dict] = defaultdict(
        lambda: {"new_signals": [], "missed_patterns": []}
    )
    processed: list[str] = []
    missing: list[str] = []
    errors: dict[str, list[str]] = {}

    for b in bundles:
        bundle_id = b["bundle_id"]
        rule_id = b["rule_id"]
        resp_path = responses_dir / f"{bundle_id}.json"
        if not resp_path.exists():
            missing.append(bundle_id)
            continue
        try:
            raw = resp_path.read_text(encoding="utf-8")
            data = json.loads(_strip_codeblock(raw))
        except json.JSONDecodeError as exc:
            errors[bundle_id] = [f"JSON parse: {exc}"]
            continue
        errs = _validate(bundle_id, rule_id, data)
        if errs:
            errors[bundle_id] = errs
        processed.append(bundle_id)

        # verdicts → jsonl
        for v in data.get("verdicts") or []:
            if not isinstance(v, dict):
                continue
            verdict_rows.append({
                "bundle_id": bundle_id,
                "rule_id": rule_id,
                "fid": v.get("fid"),
                "verdict": v.get("v"),
                "evidence": v.get("ev"),
            })
        # signals 누적
        for s in data.get("new_signals") or []:
            if isinstance(s, dict):
                s["_source_bundle"] = bundle_id
                signals_by_rule[rule_id]["new_signals"].append(s)
        for m in data.get("missed_patterns") or []:
            if isinstance(m, dict):
                m["_source_bundle"] = bundle_id
                signals_by_rule[rule_id]["missed_patterns"].append(m)

    # jsonl 출력
    dataset_path = Path(args.dataset)
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    with dataset_path.open("w", encoding="utf-8") as f:
        for row in verdict_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # signals 출력
    signals_path = Path(args.signals)
    signals_path.write_text(
        json.dumps(dict(signals_by_rule), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # progress md
    total = len(bundles)
    done = len(processed)
    pct = (done / total * 100) if total else 0
    pgs: list[str] = [
        "# Stage A 검증 진척",
        "",
        f"- 총 sub-bundle: **{total}개**",
        f"- 응답 수신: **{done}개** ({pct:.1f}%)",
        f"- 누락: **{len(missing)}개**",
        f"- 오류: **{len(errors)}개**",
        f"- verdict 행: **{len(verdict_rows):,}건** → `{args.dataset}`",
        "",
    ]
    # 룰별 진척
    by_rule_done: dict[str, list[str]] = defaultdict(list)
    by_rule_miss: dict[str, list[str]] = defaultdict(list)
    rule_total: dict[str, int] = defaultdict(int)
    for b in bundles:
        rule_total[b["rule_id"]] += 1
    for bid in processed:
        rid = bid.split("_part")[0]
        by_rule_done[rid].append(bid)
    for bid in missing:
        rid = bid.split("_part")[0]
        by_rule_miss[rid].append(bid)
    pgs += ["## 룰별", "", "| 룰 | 총 | 완료 | 누락 |", "|----|---:|---:|---:|"]
    for rid in sorted(rule_total.keys()):
        pgs.append(
            f"| `{rid}` | {rule_total[rid]} | "
            f"{len(by_rule_done.get(rid, []))} | {len(by_rule_miss.get(rid, []))} |"
        )

    if errors:
        pgs += ["", "## ⚠ 검증 오류", ""]
        for bid, errs in errors.items():
            pgs.append(f"- `{bid}`: {'; '.join(errs)}")

    if missing:
        pgs += ["", "## 누락 (응답 대기)", ""]
        pgs += [f"- `{bid}`" for bid in missing[:50]]
        if len(missing) > 50:
            pgs.append(f"- ... 외 {len(missing) - 50}개")

    Path(args.progress).write_text("\n".join(pgs) + "\n", encoding="utf-8")

    print(
        f"\n응답 {done}/{total} 통합. "
        f"verdicts={len(verdict_rows):,} / signals={sum(len(v['new_signals']) for v in signals_by_rule.values())}",
        file=sys.stderr,
    )
    print(f"  데이터셋: {args.dataset}", file=sys.stderr)
    print(f"  신호 후보: {args.signals}", file=sys.stderr)
    print(f"  진척: {args.progress}", file=sys.stderr)
    if errors:
        print(f"\n⚠ 오류 {len(errors)}개 — 진척 보고서 참고", file=sys.stderr)
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
