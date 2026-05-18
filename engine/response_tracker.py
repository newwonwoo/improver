"""LLM 응답 추적 — 던진 법령, 받은 응답, 누락/중복 식별.

기능:
- ResponseIndex: 법령명 ↔ 응답 파일 매핑 + 처리 상태 + 진척률
- scan(judgments_dir, responses_dir): 누락된 응답 / 미처리 법령 식별
- merge(): 같은 법령 응답이 여러 번 있을 때 최신 우선 + diff 로그

기대 디렉토리 구조:
    outputs/judgments/<법령명>.md     — LLM에 던질 후보
    outputs/llm_responses/<법령명>.json — 받은 응답 (한 법령 한 파일)
                                          또는 <법령명>__YYYY-MM-DD-HHMM.json (다중 응답)
    outputs/llm_responses/_index.json — 본 모듈이 관리하는 진척 인덱스
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# "법령명" 또는 "법령명__suffix" 양쪽 인식
_RESPONSE_FILE = re.compile(r"^(?P<name>.+?)(?:__(?P<suffix>.+))?\.json$")


@dataclass
class LawStatus:
    name: str
    has_judgment_md: bool = False
    response_files: list[str] = field(default_factory=list)  # 응답 파일명들
    is_processed: bool = False  # 한 개 이상의 valid 응답 있음
    last_response_ts: float | None = None
    judgments_count: int = 0      # 응답에서 처리된 finding 수
    missed_count: int = 0         # missed_findings 수
    has_overall: bool = False
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_duplicate_responses(self) -> bool:
        return len(self.response_files) > 1


def _parse_response_filename(filename: str) -> tuple[str, str | None]:
    """'법령명.json' 또는 '법령명__YYYY-MM-DD.json' 분리."""
    m = _RESPONSE_FILE.match(filename)
    if not m:
        return filename, None
    return m.group("name"), m.group("suffix")


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def scan(
    *,
    judgments_dir: Path,
    responses_dir: Path,
) -> dict[str, LawStatus]:
    """판단용 MD 디렉토리와 응답 디렉토리를 스캔해 법령별 상태 맵 반환."""
    status: dict[str, LawStatus] = {}

    # 1. judgments_dir의 .md 파일들 — 던질 후보
    if judgments_dir.exists():
        for md in judgments_dir.glob("*.md"):
            name = md.stem
            s = status.setdefault(name, LawStatus(name=name))
            s.has_judgment_md = True

    # 2. responses_dir의 .json 파일들 — 받은 응답
    if responses_dir.exists():
        for jf in responses_dir.glob("*.json"):
            if jf.name.startswith("_"):
                continue  # 인덱스 파일 등 메타
            law_name, _suffix = _parse_response_filename(jf.name)
            s = status.setdefault(law_name, LawStatus(name=law_name))
            s.response_files.append(jf.name)
            payload = _safe_load_json(jf)
            if payload is None:
                s.parse_errors.append(f"{jf.name}: JSON 파싱 실패")
                continue
            s.is_processed = True
            s.last_response_ts = max(s.last_response_ts or 0,
                                      jf.stat().st_mtime)
            s.judgments_count += len(payload.get("judgments", []) or [])
            s.missed_count += len(payload.get("missed_findings", []) or [])
            if payload.get("overall_assessment"):
                s.has_overall = True

    return status


def summarize(status: dict[str, LawStatus]) -> dict[str, Any]:
    """진척 통계."""
    total = len(status)
    has_md = sum(1 for s in status.values() if s.has_judgment_md)
    processed = sum(1 for s in status.values() if s.is_processed)
    pending = [s.name for s in status.values()
               if s.has_judgment_md and not s.is_processed]
    duplicates = [s.name for s in status.values() if s.has_duplicate_responses]
    errored = [s.name for s in status.values() if s.parse_errors]
    return {
        "total_known": total,
        "has_judgment_md": has_md,
        "processed": processed,
        "pending_count": len(pending),
        "pending_sample": pending[:20],
        "duplicates_count": len(duplicates),
        "duplicates_sample": duplicates[:10],
        "errored_count": len(errored),
        "errored_sample": errored[:10],
        "progress_rate": round(processed / has_md, 4) if has_md else 0,
    }


def write_index(index: dict[str, LawStatus], path: Path) -> None:
    """LawStatus map을 JSON으로 저장."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": int(time.time()),
        "summary": summarize(index),
        "laws": {name: asdict(s) for name, s in sorted(index.items())},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def latest_response_path(
    name: str, responses_dir: Path
) -> Path | None:
    """한 법령에 여러 응답 파일이 있을 때 가장 최신 파일 반환 (mtime 기준)."""
    candidates = []
    for jf in responses_dir.glob("*.json"):
        if jf.name.startswith("_"):
            continue
        law_name, _ = _parse_response_filename(jf.name)
        if law_name == name:
            candidates.append(jf)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)
