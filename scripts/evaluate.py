#!/usr/bin/env python3
"""정밀도 평가 (핵심 설계서 §4.5).

사용법:
    python scripts/evaluate.py --goldset data/goldset/<file>.json \\
                               --laws-dir fixtures/

각 골드셋 항목 (law, article, pattern_id, label)에 대해 엔진을 돌려
TP/FP 카운트 → 패턴별/전체 Precision 산출.
재현율(Recall)은 미탐 측정이 어려워 골드셋에 명시된 항목만 검증.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import fpc, scorer  # noqa: E402
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


def _scan(law_name: str, text: str):
    law = parse_law(text, name=law_name, law_category=_detect_category(law_name))
    findings = run_all(law)
    findings = fpc.correct(law, findings)
    result = scorer.compute(law, findings)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="골드셋 정밀도 평가")
    parser.add_argument("--goldset", required=True, help="골드셋 JSON 경로")
    parser.add_argument("--laws-dir", default="fixtures",
                        help="법령 텍스트가 들어있는 디렉토리 (파일명 = 법령명.txt)")
    parser.add_argument("--report", default="-", help="결과 출력 (기본 stdout)")
    args = parser.parse_args(argv)

    goldset = json.loads(Path(args.goldset).read_text(encoding="utf-8"))
    items = [i for i in goldset["items"] if i.get("label") != "BORDER"]

    laws_dir = Path(args.laws_dir)
    file_overrides = goldset.get("law_files", {})
    cache: dict[str, set[tuple[str, str]]] = {}
    missing: list[str] = []

    def _detections_for(law_name: str) -> set[tuple[str, str]]:
        if law_name in cache:
            return cache[law_name]
        candidates = []
        if law_name in file_overrides:
            candidates.append(laws_dir / file_overrides[law_name])
        candidates += [
            laws_dir / f"{law_name}.txt",
            laws_dir / f"synthetic_{law_name}.txt",
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            missing.append(law_name)
            cache[law_name] = set()
            return set()
        result = _scan(law_name, path.read_text(encoding="utf-8"))
        detections = {
            (f.article_number, f.pattern_id)
            for f in result.findings
            if not f.is_false_positive
        }
        cache[law_name] = detections
        return detections

    per_pattern_tp: dict[str, int] = defaultdict(int)
    per_pattern_fp: dict[str, int] = defaultdict(int)
    per_pattern_missed_tp: dict[str, int] = defaultdict(int)
    per_pattern_correct_fp: dict[str, int] = defaultdict(int)

    for item in items:
        law_name = item["law"]
        article = item["article"]
        pid = item["pattern_id"]
        label = item["label"]
        detected = (article, pid) in _detections_for(law_name)

        if label == "TP":
            if detected:
                per_pattern_tp[pid] += 1
            else:
                per_pattern_missed_tp[pid] += 1
        elif label == "FP":
            if detected:
                # 엔진이 잡았는데 골드셋은 오탐이라고 라벨링 → 엔진 오탐
                per_pattern_fp[pid] += 1
            else:
                # 엔진이 잘 걸러냄
                per_pattern_correct_fp[pid] += 1

    rows = []
    total_tp = total_fp = total_miss = 0
    for pid in sorted(
        set(per_pattern_tp) | set(per_pattern_fp)
        | set(per_pattern_missed_tp) | set(per_pattern_correct_fp)
    ):
        tp = per_pattern_tp[pid]
        fp = per_pattern_fp[pid]
        miss = per_pattern_missed_tp[pid]
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + miss) if (tp + miss) else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall else None
        )
        rows.append({
            "pattern_id": pid,
            "tp": tp,
            "fp": fp,
            "missed_tp": miss,
            "correctly_filtered_fp": per_pattern_correct_fp[pid],
            "precision": round(precision, 3) if precision is not None else None,
            "recall": round(recall, 3) if recall is not None else None,
            "f1": round(f1, 3) if f1 is not None else None,
        })
        total_tp += tp
        total_fp += fp
        total_miss += miss

    overall = {
        "tp": total_tp,
        "fp": total_fp,
        "missed_tp": total_miss,
        "precision": (
            round(total_tp / (total_tp + total_fp), 3)
            if (total_tp + total_fp) else None
        ),
        "recall": (
            round(total_tp / (total_tp + total_miss), 3)
            if (total_tp + total_miss) else None
        ),
    }
    output = {"per_pattern": rows, "overall": overall, "missing_laws": missing}
    payload = json.dumps(output, ensure_ascii=False, indent=2)
    if args.report == "-":
        sys.stdout.write(payload + "\n")
    else:
        Path(args.report).write_text(payload, encoding="utf-8")
        print(f"Wrote {args.report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
