"""config 파일 무결성 검증.

자동 갱신 후 또는 사람이 손으로 편집한 후 config가 깨지지 않았는지 확인.

검증 항목:
- recommendations.json: 패턴 ID 형식 + 5개 등급(심각/경고/주의/개선/양호) 완비
- patterns.json: 알려진 패턴만 / thresholds 키 일관성
- disciplinary_cases.json: 필수 필드(case_id, agency, summary) + 중복 ID 검출
- sub_check_agencies.json: 알려진 기관명 / sub_check 형식 (X-NN-x)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_KNOWN_PATTERNS = {
    "S-01", "S-02", "S-03", "S-04",
    "F-01", "F-02", "F-03", "F-04", "F-05",
    "L-01", "L-02", "L-03",
    "G-01", "G-02", "G-03", "G-04", "G-05",
    "E-01", "E-02", "E-03", "E-04", "E-05",
    "X-CROSS", "X-PATTERN",  # 메타 패턴
}
_KNOWN_SEVERITIES = {"심각", "경고", "주의", "개선", "양호"}
_KNOWN_AGENCIES = {"법제처", "감사원", "공정위", "권익위", "금감원", "인권위",
                    "국토교통부", "보건복지부", "고용노동부"}
_SUBCHECK_RE = re.compile(r"^[A-Z]-\d{2}-[a-z]$")


@dataclass
class ValidationReport:
    file: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_recommendations(path: Path) -> ValidationReport:
    rep = ValidationReport(file=str(path))
    if not path.exists():
        rep.errors.append("파일 없음")
        return rep
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        rep.errors.append(f"JSON 파싱 실패: {e}")
        return rep
    if not isinstance(data, dict):
        rep.errors.append("최상위가 dict 아님")
        return rep
    for pid, per_sev in data.items():
        if pid not in _KNOWN_PATTERNS:
            rep.warnings.append(f"미지의 패턴 ID: {pid}")
        if not isinstance(per_sev, dict):
            rep.errors.append(f"{pid}: 값이 dict가 아님")
            continue
        missing = _KNOWN_SEVERITIES - set(per_sev.keys())
        if missing:
            rep.warnings.append(f"{pid}: 등급 누락 {missing}")
        for sev, text in per_sev.items():
            if sev not in _KNOWN_SEVERITIES:
                rep.warnings.append(f"{pid}: 미지의 등급 {sev}")
            if not isinstance(text, str) or len(text) < 5:
                rep.errors.append(f"{pid}/{sev}: 권고 텍스트 부적절")
    return rep


def validate_patterns(path: Path) -> ValidationReport:
    rep = ValidationReport(file=str(path))
    if not path.exists():
        rep.errors.append("파일 없음")
        return rep
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        rep.errors.append(f"JSON 파싱 실패: {e}")
        return rep
    if not isinstance(data, dict):
        # engine.json 같은 다른 형식일 수도 있어 dict 아니면 그냥 통과
        return rep
    for pid, entry in data.items():
        if pid in {"parser", "rule_engine", "llm_engine", "mcp_engine",
                    "scoring", "report"}:
            continue  # engine.json 영역 키
        if pid not in _KNOWN_PATTERNS:
            rep.warnings.append(f"미지의 패턴 ID: {pid}")
        if not isinstance(entry, dict):
            continue
        if "thresholds" in entry and not isinstance(entry["thresholds"], dict):
            rep.errors.append(f"{pid}: thresholds가 dict 아님")
    return rep


def validate_cases(path: Path) -> ValidationReport:
    rep = ValidationReport(file=str(path))
    if not path.exists():
        rep.errors.append("파일 없음")
        return rep
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        rep.errors.append(f"JSON 파싱 실패: {e}")
        return rep
    cases = data.get("cases", [])
    if not isinstance(cases, list):
        rep.errors.append("cases가 list 아님")
        return rep
    ids = set()
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            rep.errors.append(f"cases[{i}]: dict 아님")
            continue
        for req in ("case_id", "agency", "summary"):
            if not c.get(req):
                rep.errors.append(f"cases[{i}]: 필수 필드 '{req}' 누락")
        cid = c.get("case_id")
        if cid and cid in ids:
            rep.errors.append(f"중복 case_id: {cid}")
        if cid:
            ids.add(cid)
        if c.get("agency") and c["agency"] not in _KNOWN_AGENCIES:
            rep.warnings.append(f"cases[{i}] 미지의 기관: {c['agency']}")
        for p in c.get("related_patterns", []):
            if p not in _KNOWN_PATTERNS:
                rep.warnings.append(f"cases[{i}] 미지의 pattern: {p}")
    return rep


def validate_sub_check_agencies(path: Path) -> ValidationReport:
    rep = ValidationReport(file=str(path))
    if not path.exists():
        rep.errors.append("파일 없음")
        return rep
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        rep.errors.append(f"JSON 파싱 실패: {e}")
        return rep
    for sub, agencies in data.items():
        if not _SUBCHECK_RE.match(sub):
            rep.warnings.append(f"sub_check 형식 비표준: {sub}")
        pattern_prefix = sub.rsplit("-", 1)[0]
        if pattern_prefix not in _KNOWN_PATTERNS:
            rep.warnings.append(f"{sub}: 미지 패턴")
        if not isinstance(agencies, list):
            rep.errors.append(f"{sub}: 기관 목록이 list 아님")
            continue
        for a in agencies:
            if a not in _KNOWN_AGENCIES:
                rep.warnings.append(f"{sub}: 미지 기관 '{a}'")
    return rep


def validate_all(config_dir: Path) -> list[ValidationReport]:
    reports = [
        validate_recommendations(config_dir / "recommendations.json"),
        validate_patterns(config_dir / "patterns.json"),
        validate_cases(config_dir / "disciplinary_cases.json"),
        validate_sub_check_agencies(config_dir / "sub_check_agencies.json"),
    ]
    return reports
