"""두 분석 결과 디렉토리를 비교 — 엔진 강화 전/후 효과 측정.

비교 항목:
- 등급 분포 변화 (F→D, D→C 등 시프트)
- 패턴별 finding 수 / FP 마킹 변화
- 평균 점수 변화
- 새로 추가/제거된 finding 수
- LLM이 갱신한 권고안 수
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load_results(d: Path) -> dict[str, dict]:
    """results 디렉토리에서 법령명 → result dict 매핑 로드."""
    out: dict[str, dict] = {}
    if not d.exists():
        return out
    for p in d.glob("*.json"):
        if p.name.startswith("_") or p.stem in {"batch_summary", "batch_import_summary"}:
            continue
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
    return out


def _result_stats(result: dict) -> dict[str, Any]:
    findings = result.get("findings", [])
    real = [f for f in findings if not f.get("is_false_positive")]
    fps = [f for f in findings if f.get("is_false_positive")]
    by_pattern = Counter(f["pattern_id"] for f in real)
    by_severity = Counter(f["severity"] for f in real)
    layer3_count = sum(
        1 for f in findings
        if isinstance(f.get("recommendation"), dict)
        and f["recommendation"].get("layer") == 3
    )
    return {
        "law_score": result.get("law_score"),
        "law_grade": result.get("law_grade"),
        "n_total": len(findings),
        "n_real": len(real),
        "n_fp": len(fps),
        "by_pattern": dict(by_pattern),
        "by_severity": dict(by_severity),
        "layer3_recommendations": layer3_count,
    }


def compare(before_dir: Path, after_dir: Path) -> dict[str, Any]:
    """before / after 두 디렉토리 비교 통계."""
    before = _load_results(before_dir)
    after = _load_results(after_dir)
    common = sorted(set(before) & set(after))
    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))

    grade_transitions: Counter = Counter()
    score_deltas: list[float] = []
    fp_count_before = 0
    fp_count_after = 0
    finding_count_before = 0
    finding_count_after = 0
    layer3_before = 0
    layer3_after = 0
    pattern_count_before: Counter = Counter()
    pattern_count_after: Counter = Counter()
    severity_before: Counter = Counter()
    severity_after: Counter = Counter()

    per_law_changes: list[dict] = []

    for name in common:
        b = _result_stats(before[name])
        a = _result_stats(after[name])
        transition = f"{b['law_grade']}→{a['law_grade']}"
        grade_transitions[transition] += 1
        if b["law_score"] is not None and a["law_score"] is not None:
            score_deltas.append(a["law_score"] - b["law_score"])
        fp_count_before += b["n_fp"]
        fp_count_after += a["n_fp"]
        finding_count_before += b["n_real"]
        finding_count_after += a["n_real"]
        layer3_before += b["layer3_recommendations"]
        layer3_after += a["layer3_recommendations"]
        for p, c in b["by_pattern"].items():
            pattern_count_before[p] += c
        for p, c in a["by_pattern"].items():
            pattern_count_after[p] += c
        for s, c in b["by_severity"].items():
            severity_before[s] += c
        for s, c in a["by_severity"].items():
            severity_after[s] += c
        if transition != f"{b['law_grade']}→{b['law_grade']}" or abs(
            (a["law_score"] or 0) - (b["law_score"] or 0)
        ) >= 10:
            per_law_changes.append({
                "law": name,
                "grade_change": transition,
                "score_before": b["law_score"],
                "score_after": a["law_score"],
                "delta": (a["law_score"] or 0) - (b["law_score"] or 0),
                "fp_added": a["n_fp"] - b["n_fp"],
            })

    pattern_delta = {
        p: {
            "before": pattern_count_before.get(p, 0),
            "after": pattern_count_after.get(p, 0),
            "delta": pattern_count_after.get(p, 0) - pattern_count_before.get(p, 0),
        }
        for p in sorted(set(pattern_count_before) | set(pattern_count_after))
    }

    avg_delta = sum(score_deltas) / len(score_deltas) if score_deltas else 0
    per_law_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)

    return {
        "common_laws": len(common),
        "only_before": len(only_before),
        "only_after": len(only_after),
        "avg_score_delta": round(avg_delta, 2),
        "fp_count_before": fp_count_before,
        "fp_count_after": fp_count_after,
        "fp_increase": fp_count_after - fp_count_before,
        "finding_count_before": finding_count_before,
        "finding_count_after": finding_count_after,
        "layer3_before": layer3_before,
        "layer3_after": layer3_after,
        "grade_transitions": dict(grade_transitions.most_common(20)),
        "severity_before": dict(severity_before),
        "severity_after": dict(severity_after),
        "pattern_delta": pattern_delta,
        "top_changes": per_law_changes[:30],
    }
