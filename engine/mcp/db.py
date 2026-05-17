"""로컬 법령 인덱스 (엔진 설계서 §5.1~§5.3).

검증 가능한 최소 인덱스를 data/indexes/law_index.json + repealed_laws.json으로 관리.
PR #4 단계에서는 수동 등록 50건 정도면 충분; legalize-kr 1,680건 통합은 후속 작업.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "indexes"
_LAW_INDEX_PATH = _DATA_DIR / "law_index.json"
_REPEALED_PATH = _DATA_DIR / "repealed_laws.json"


@dataclass
class ArticleExistence:
    exists: bool
    status: str            # exists|not_found|law_repealed|law_renamed|unknown
    current_law_name: str | None = None
    note: str | None = None


@dataclass
class DecreeCoverage:
    decree_exists: bool
    decree_name: str | None = None
    coverage: str = "none"   # full|partial|none
    matched_decree_articles: list[str] | None = None
    note: str | None = None


class LawIndex:
    """법령명/약칭 → article_numbers, has_enforcement_decree 매핑."""

    def __init__(self, laws: list[dict], repealed: dict | None = None):
        self._laws: dict[str, dict] = {}
        self._aliases: dict[str, str] = {}
        for entry in laws:
            name = entry["name"]
            self._laws[name] = entry
            for alias in entry.get("short_names", []):
                self._aliases[alias] = name
        self._repealed = repealed or {"폐지": [], "제명변경": []}

    def find(self, law_name: str) -> dict | None:
        if law_name in self._laws:
            return self._laws[law_name]
        if law_name in self._aliases:
            return self._laws[self._aliases[law_name]]
        return None

    def has_article(self, law_name: str, article_num: str) -> ArticleExistence:
        entry = self.find(law_name)
        if entry is None:
            # 폐지/제명변경 확인
            for r in self._repealed.get("폐지", []):
                if r["name"] == law_name:
                    return ArticleExistence(
                        exists=False,
                        status="law_repealed",
                        current_law_name=r.get("successor"),
                        note=f"{law_name}은 {r['repealed_date']}부로 폐지됨.",
                    )
            for r in self._repealed.get("제명변경", []):
                if r["old_name"] == law_name:
                    return ArticleExistence(
                        exists=False,
                        status="law_renamed",
                        current_law_name=r["new_name"],
                        note=f"{law_name}은 '{r['new_name']}'으로 제명 변경됨.",
                    )
            return ArticleExistence(exists=False, status="unknown")
        if article_num in entry.get("article_numbers", []):
            return ArticleExistence(exists=True, status="exists", current_law_name=entry["name"])
        return ArticleExistence(
            exists=False,
            status="not_found",
            current_law_name=entry["name"],
            note=f"{entry['name']}에 제{article_num}조 미존재.",
        )

    def decree_for(self, law_name: str) -> dict | None:
        entry = self.find(law_name)
        if not entry or not entry.get("has_enforcement_decree"):
            return None
        decree_name = entry.get("enforcement_decree_name")
        if not decree_name:
            return None
        return self._laws.get(decree_name)


def _load_json(path: Path) -> list | dict:
    if not path.exists():
        return [] if path.name.endswith("_index.json") else {}
    with path.open(encoding="utf-8") as fp:
        return json.load(fp)


def load_default_index() -> LawIndex:
    laws_doc = _load_json(_LAW_INDEX_PATH)
    laws = laws_doc.get("laws", []) if isinstance(laws_doc, dict) else laws_doc
    repealed = _load_json(_REPEALED_PATH)
    return LawIndex(laws=laws, repealed=repealed if isinstance(repealed, dict) else {})


# ── Tool 1 / Tool 2 (설계서 §5.2, §5.3) ────────────────────────────────────


def check_article_exists(
    law_name: str, article_num: str, *, index: LawIndex | None = None
) -> ArticleExistence:
    idx = index or load_default_index()
    return idx.has_article(law_name, article_num)


def check_enforcement_decree(
    law_name: str, article_num: str, *, index: LawIndex | None = None,
) -> DecreeCoverage:
    idx = index or load_default_index()
    parent = idx.find(law_name)
    if parent is None:
        return DecreeCoverage(decree_exists=False, coverage="none",
                              note=f"{law_name} 인덱스에 없음.")
    if not parent.get("has_enforcement_decree"):
        return DecreeCoverage(decree_exists=False, coverage="none",
                              note="시행령 자체 미제정.")
    decree_entry = idx.decree_for(law_name)
    if decree_entry is None:
        return DecreeCoverage(decree_exists=True, coverage="none",
                              decree_name=parent.get("enforcement_decree_name"),
                              note="시행령 인덱스 미수록.")
    # 단순 휴리스틱: 시행령에 동일 조문번호(±3) 존재하면 partial, 정확 일치하면 full
    decree_arts = decree_entry.get("article_numbers", [])
    matched = [a for a in decree_arts if a == article_num]
    if matched:
        coverage = "full"
    else:
        try:
            base = int(article_num)
            near = [str(a) for a in decree_arts if str(a).isdigit() and abs(int(a) - base) <= 3]
        except ValueError:
            near = []
        if near:
            coverage = "partial"
            matched = near
        else:
            coverage = "none"
    return DecreeCoverage(
        decree_exists=True,
        decree_name=decree_entry["name"],
        coverage=coverage,
        matched_decree_articles=matched,
    )
