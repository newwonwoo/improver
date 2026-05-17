"""Layer 2 — 사례 DB + 기관 매핑 (핵심 설계서 §2.4).

Finding의 pattern_id/sub_check_id에 따라 disciplinary_cases.json에서
유사 사례를 찾아 Finding.recommendation에 부착.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import AnalysisResult, Finding

_CASES_PATH = Path(__file__).resolve().parent.parent / "config" / "disciplinary_cases.json"
_AGENCIES_PATH = Path(__file__).resolve().parent.parent / "config" / "sub_check_agencies.json"


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cases() -> list[dict]:
    payload = _load_json(_CASES_PATH)
    if not payload:
        return []
    return payload.get("cases", [])


def _load_agencies() -> dict[str, list[str]]:
    return _load_json(_AGENCIES_PATH) or {}


def _match(finding: Finding, case: dict) -> bool:
    if finding.pattern_id in case.get("related_patterns", []):
        return True
    sub_check = (finding.recommendation or {}).get("sub_check_id")
    if sub_check and sub_check in case.get("related_sub_checks", []):
        return True
    return False


def _agency_for(finding: Finding, agency_map: dict[str, list[str]]) -> list[str]:
    sub_check = (finding.recommendation or {}).get("sub_check_id")
    if sub_check and sub_check in agency_map:
        return agency_map[sub_check]
    # pattern_id 접두 매칭 (서브체크 미지정 시)
    pattern = finding.pattern_id
    for key, agencies in agency_map.items():
        if key.startswith(pattern + "-"):
            return agencies
    return []


def attach(result: AnalysisResult) -> AnalysisResult:
    """결과의 각 finding에 사례·기관 매칭을 부착."""
    cases = _load_cases()
    agency_map = _load_agencies()
    for f in result.findings:
        if f.is_false_positive:
            continue
        matched_cases = [
            {
                "case_id": c["case_id"],
                "agency": c["agency"],
                "date": c["date"],
                "target": c["target"],
                "summary": c["summary"],
                "sanction": c["sanction_type"],
                "agency_basis": c.get("agency_basis"),
                "url": c.get("url"),
            }
            for c in cases
            if _match(f, c)
        ][:3]
        agencies = _agency_for(f, agency_map)
        rec = dict(f.recommendation or {})
        if matched_cases:
            rec["matched_cases"] = matched_cases
            # P-06: 첫 사례의 기관 근거를 reference_note로 노출
            primary = matched_cases[0]
            if primary.get("agency_basis"):
                rec.setdefault("reference_note",
                               f"{primary['agency']}: {primary['agency_basis']}")
        if agencies:
            rec["related_agencies"] = agencies
        if matched_cases or agencies:
            f.recommendation = rec
    return result
