"""E-04 유형별 규제 차등 (법령 단위, 사전 키워드 기반)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding

_DICT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "type_keywords.json"


def _load_dict() -> dict[str, list[str]]:
    if not _DICT_PATH.exists():
        return {}
    with _DICT_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)


class E04Differential:
    pattern_id = "E-04"
    pattern_name = "유형별 규제 차등"
    category = "효율성"

    _TYPE_DICT: ClassVar[dict[str, list[str]]] = _load_dict()

    def scan(self, law: Law) -> list[Finding]:
        keywords = self._TYPE_DICT.get(law.name)
        if not keywords:
            return []
        full = "\n".join(a.full_text for a in law.articles)
        present = [k for k in keywords if k in full]
        if len(present) < 3:
            return []
        if len(present) >= 7:
            severity = "심각"
        elif len(present) >= 5:
            severity = "경고"
        else:
            severity = "주의"
        return [
            make_finding(
                self,
                1,
                PatternResult(
                    article=law.articles[0],
                    severity=severity,
                    matched_text=", ".join(present),
                    summary=f"유형 {len(present)}종 차등 규제",
                    fix_type="replace",
                ),
            )
        ]
