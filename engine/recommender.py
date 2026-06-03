"""Layer 1 표준 권고안 적용 (핵심 설계서 §2.3).

config/recommendations.json에서 {pattern_id, severity} → 권고 문장 조회.
"""
from __future__ import annotations

import json
from pathlib import Path

from .schema import AnalysisResult

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "recommendations.json"


def _load_templates() -> dict[str, dict[str, str]]:
    with _CONFIG_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)


def apply(result: AnalysisResult) -> AnalysisResult:
    """Layer 1 표준 권고안을 부착. 이미 Layer 3가 적용된 finding은 보존."""
    templates = _load_templates()
    for f in result.findings:
        per_pattern = templates.get(f.pattern_id, {})
        text = per_pattern.get(f.severity)
        if not text:
            continue
        existing = f.recommendation or {}
        existing["template"] = text
        # Layer 3 (LLM 맞춤)가 이미 부착되었으면 격상 유지
        if existing.get("layer") != 3:
            existing["layer"] = 1
        f.recommendation = existing
    return result
