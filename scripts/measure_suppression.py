#!/usr/bin/env python3
"""S5 — R-DELEG-BLANKET FP필터(시행령·시행규칙 한정열거) 억제 효과 측정.

샘플 법령에 대해:
  - R-DELEG-BLANKET 발생 수 (필터 적용 후)
  - has_sublaw_concrete_enum 으로 억제된 수 (필터 활동량)
  - 억제율
슈퍼바이저 '과억제 감시'용 베이스 지표. 사용:
    python scripts/measure_suppression.py [N]   # 앞 N개 법령(기본 500)
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.parser import parse_law
from engine.structure import decompose
from engine.slm import features as F
from engine.slm.features import extract_features, enrich_with_sublaw
from engine.reasoning.inference import reason_over

RAW = ROOT / "data/laws/raw"


def _load(d: Path):
    p = d / "법률.md"
    if not p.exists():
        return None
    t = p.read_text(encoding="utf-8", errors="replace")
    if t.lstrip().startswith("---"):
        parts = t.split("---", 2)
        if len(parts) >= 3:
            t = parts[2]
    try:
        return parse_law(t, name=d.name)
    except Exception:
        return None


def _rule_ids(fv):
    r = reason_over(fv)
    if hasattr(r, "steps"):
        return [s.rule_id for s in r.steps]
    return [s.rule_id for cat in r.by_category().values() for s in cat]


def measure(n: int = 500) -> dict:
    """두 번 추론(필터 신호 off/on)으로 '진짜 억제'만 집계.

    baseline = 신호 off 시 R-DELEG-BLANKET 발생(=필터 없을 때).
    fired    = 신호 on(실제) 발생.
    suppressed = baseline 발생했으나 필터로 사라진 것 (= 위임 충전 FP후보).
    """
    dirs = sorted([d for d in RAW.iterdir() if d.is_dir()])[:n]
    baseline = fired = suppressed = articles = 0
    F._SUBLAW_CACHE.clear()
    for d in dirs:
        law = _load(d)
        if law is None:
            continue
        for art in law.articles:
            articles += 1
            fv = extract_features(art, decompose(art), law=law)
            if law.name:
                enrich_with_sublaw(fv, law.name, art.number)
            on = "R-DELEG-BLANKET" in _rule_ids(fv)
            saved = getattr(fv, "has_sublaw_concrete_enum", 0.0)
            fv.has_sublaw_concrete_enum = 0.0          # 필터 off 베이스라인
            off = "R-DELEG-BLANKET" in _rule_ids(fv)
            fv.has_sublaw_concrete_enum = saved
            if off:
                baseline += 1
            if on:
                fired += 1
            if off and not on:
                suppressed += 1
    return {
        "laws": len(dirs),
        "articles": articles,
        "baseline_fired_no_filter": baseline,
        "fired_with_filter": fired,
        "suppressed_true_FP_candidates": suppressed,
        "suppression_rate_pct": round(suppressed / baseline * 100, 1) if baseline else 0.0,
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    import json
    print(json.dumps(measure(n), ensure_ascii=False, indent=2))
