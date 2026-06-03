"""검토된 후보(사례·권고 템플릿)를 config에 병합.

사람이 outputs/feedback/{case,template}_candidates.json에서 후보별로
"approved": true 표시한 것만 실제 config 파일에 병합한다.

설계 원칙:
- 백업 자동 생성 (config 파일을 .bak.YYYYMMDD-HHMMSS로 복사)
- dry-run 모드 — 변경 사항만 출력하고 파일은 안 건드림
- 멱등 — 같은 후보를 두 번 적용해도 중복 추가 안 함
- 충돌 처리 — 사례는 case_id 중복 시 skip / 템플릿은 사용자 선택(--overwrite)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ApplyReport:
    cases_added: list[str] = field(default_factory=list)
    cases_skipped: list[str] = field(default_factory=list)
    templates_added: list[str] = field(default_factory=list)  # "pattern/severity"
    templates_replaced: list[str] = field(default_factory=list)
    templates_skipped: list[str] = field(default_factory=list)
    backups_created: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "cases_added": len(self.cases_added),
            "cases_skipped": len(self.cases_skipped),
            "templates_added": len(self.templates_added),
            "templates_replaced": len(self.templates_replaced),
            "templates_skipped": len(self.templates_skipped),
        }


def _backup(path: Path, report: ApplyReport, dry_run: bool) -> Path:
    suffix = time.strftime(".bak.%Y%m%d-%H%M%S")
    bak = path.with_name(path.name + suffix)
    if not dry_run:
        bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    report.backups_created.append(str(bak))
    return bak


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _is_approved(candidate: dict) -> bool:
    """후보가 approve 마킹됐는지. 'approved' 키 명시 또는 True 값."""
    val = candidate.get("approved")
    return val is True or (isinstance(val, str) and val.lower() in {"true", "yes", "y", "ok"})


def apply_case_candidates(
    *,
    candidates_path: Path,
    target_path: Path,
    dry_run: bool = False,
) -> ApplyReport:
    """case_candidates.json에서 approved=True인 항목만 disciplinary_cases.json에 병합."""
    report = ApplyReport()
    if not candidates_path.exists():
        return report

    candidates_doc = _load_json(candidates_path, {"candidates": []})
    candidates = candidates_doc.get("candidates", [])

    target_doc = _load_json(target_path, {"cases": []})
    existing_ids = {c.get("case_id") for c in target_doc.get("cases", [])}

    new_cases: list[dict] = []
    for c in candidates:
        if not _is_approved(c):
            continue
        cid = c.get("case_id")
        if not cid:
            report.cases_skipped.append("(no case_id)")
            continue
        if cid in existing_ids:
            report.cases_skipped.append(cid)
            continue
        # 후보 → 표준 사례 스키마 변환
        new_cases.append({
            "case_id": cid,
            "agency": c["agency"],
            "agency_type": c.get("agency_type", "감사"),
            "date": c.get("date"),
            "target": c.get("source_law"),
            "target_industry": c.get("target_industry"),
            "related_patterns": c.get("related_patterns", []),
            "related_sub_checks": c.get("related_sub_checks", []),
            "summary": c.get("summary", ""),
            "sanction_type": c.get("sanction_type", "(미상)"),
            "sanction_detail": c.get("sanction_detail"),
            "law_reference": c.get("law_reference"),
            "agency_basis": c.get("agency_basis"),
            "url": c.get("url"),
            "keywords": c.get("keywords", []),
        })
        report.cases_added.append(cid)
        existing_ids.add(cid)

    if new_cases and not dry_run:
        _backup(target_path, report, dry_run=False)
        target_doc.setdefault("cases", []).extend(new_cases)
        target_path.write_text(
            json.dumps(target_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report


def apply_template_candidates(
    *,
    candidates_path: Path,
    target_path: Path,
    overwrite: bool = False,
    dry_run: bool = False,
) -> ApplyReport:
    """template_candidates.json에서 approved=True인 항목만 recommendations.json에 병합.

    overwrite=False: 기존 (pattern, severity) 템플릿이 있으면 skip (default)
    overwrite=True:  기존 템플릿을 후보로 덮어쓰기
    """
    report = ApplyReport()
    if not candidates_path.exists():
        return report

    candidates_doc = _load_json(candidates_path, {"candidates": []})
    candidates = candidates_doc.get("candidates", [])

    target_doc = _load_json(target_path, {})

    changed = False
    for c in candidates:
        if not _is_approved(c):
            continue
        pid = c.get("pattern_id")
        sev = c.get("severity")
        new_text = c.get("suggested_template") or c.get("approved_text")
        if not (pid and sev and new_text):
            report.templates_skipped.append(f"{pid}/{sev} (필드 누락)")
            continue
        existing = (target_doc.get(pid) or {}).get(sev)
        if existing and not overwrite:
            report.templates_skipped.append(f"{pid}/{sev} (existing, --overwrite 필요)")
            continue
        target_doc.setdefault(pid, {})[sev] = new_text
        if existing:
            report.templates_replaced.append(f"{pid}/{sev}")
        else:
            report.templates_added.append(f"{pid}/{sev}")
        changed = True

    if changed and not dry_run:
        _backup(target_path, report, dry_run=False)
        target_path.write_text(
            json.dumps(target_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report
