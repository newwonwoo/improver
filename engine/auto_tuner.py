"""tuning_proposals.json의 명확한 항목을 config/patterns.json에 자동 적용.

자동 적용 기준 (엄격):
- threshold_proposals: n >= 30 + |avg_delta| >= 1.0 (강한 시그널)
- fp_filter_proposals: n >= 30 + fp_rate >= 0.6 (확실한 과탐)

위 조건 미달은 사람 검토용으로 남김. 자동 적용 결과는 백업 후 patterns.json 갱신.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_STRONG_DELTA_MIN_N = 30
_STRONG_DELTA_MIN_ABS = 1.0
_STRONG_FP_MIN_N = 30
_STRONG_FP_MIN_RATE = 0.6


@dataclass
class TuneReport:
    threshold_changes: list[dict] = field(default_factory=list)
    fp_filter_changes: list[dict] = field(default_factory=list)
    skipped_for_review: list[dict] = field(default_factory=list)
    backup_path: str | None = None


def _backup(path: Path) -> Path:
    suffix = time.strftime(".bak.%Y%m%d-%H%M%S")
    bak = path.with_name(path.name + suffix)
    if path.exists():
        bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return bak


def auto_tune(
    *,
    proposals_path: Path,
    patterns_config_path: Path,
    dry_run: bool = False,
) -> TuneReport:
    """tuning_proposals.json → patterns.json 자동 갱신."""
    report = TuneReport()
    if not proposals_path.exists():
        return report
    proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
    patterns = (
        json.loads(patterns_config_path.read_text(encoding="utf-8"))
        if patterns_config_path.exists() else {}
    )

    # 1. threshold_proposals — 등급 시프트가 강하면 임계치 한 단계 조정
    for p in proposals.get("threshold_proposals", []):
        pid = p["pattern_id"]
        delta = p["avg_delta"]
        n = p["n"]
        if n < _STRONG_DELTA_MIN_N or abs(delta) < _STRONG_DELTA_MIN_ABS:
            report.skipped_for_review.append({**p, "reason": "신호 약함"})
            continue
        # delta > 0: LLM이 상향 → 룰 등급 임계치 낮춰서 더 잡게 (위험: skip)
        # delta < 0: LLM이 하향 → 룰 등급 임계치 올려서 덜 잡게 (안전한 방향)
        if delta > 0:
            report.skipped_for_review.append({**p, "reason": "상향 자동 적용 안 함"})
            continue
        # patterns.json에 thresholds 키가 있는 경우만 (S-01/S-04/E-04 등)
        entry = patterns.setdefault(pid, {"enabled": True, "thresholds": {}})
        if "thresholds" not in entry:
            report.skipped_for_review.append({**p, "reason": "thresholds 키 없음 — 수동 보강"})
            continue
        # 단순 정책: 모든 임계치를 일정 비율 상향 (덜 엄격하게)
        adjust = 1.1 if delta < -1.5 else 1.05
        before = dict(entry["thresholds"])
        for k, v in list(entry["thresholds"].items()):
            try:
                entry["thresholds"][k] = round(v * adjust, 2)
            except TypeError:
                continue
        report.threshold_changes.append({
            "pattern_id": pid,
            "delta": delta,
            "n": n,
            "before": before,
            "after": dict(entry["thresholds"]),
            "adjust_factor": adjust,
        })

    # 2. fp_filter_proposals — 강한 과탐 패턴 disable_for_<reason> 플래그 추가
    for p in proposals.get("fp_filter_proposals", []):
        pid = p["pattern_id"]
        rate = p["fp_rate"]
        n = p["n"]
        if n < _STRONG_FP_MIN_N or rate < _STRONG_FP_MIN_RATE:
            report.skipped_for_review.append({**p, "reason": "신호 약함"})
            continue
        entry = patterns.setdefault(pid, {"enabled": True})
        # 자동으로 disable하지는 않음 — 플래그만 표시
        entry["fp_warning"] = {
            "rate": rate,
            "n_observed": n,
            "top_reasons": p.get("top_reasons"),
            "recommended_action": "FPC 강화 또는 키워드 필터 추가",
        }
        report.fp_filter_changes.append({"pattern_id": pid, "fp_rate": rate})

    # 백업 + 저장
    if (report.threshold_changes or report.fp_filter_changes) and not dry_run:
        report.backup_path = str(_backup(patterns_config_path))
        patterns_config_path.parent.mkdir(parents=True, exist_ok=True)
        patterns_config_path.write_text(
            json.dumps(patterns, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report
