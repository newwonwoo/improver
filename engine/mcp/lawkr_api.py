"""법제처 법령정보센터 API fallback (엔진 설계서 §5.4).

로컬 인덱스에 없을 때만 호출. 응답은 로컬 캐시(JSON)에 누적.
네트워크 차단 환경에서는 graceful fallback — 호출 자체가 실패해도 ArticleExistence(unknown).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .db import ArticleExistence


_DEFAULT_CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "indexes" / "lawkr_cache.json"
_BASE_URL = "http://www.law.go.kr/DRF/lawSearch.do"
_DAILY_LIMIT = 100
_SLEEP_BETWEEN = 1.0  # 초당 1회 제한 (비공식)


@dataclass
class APIQuota:
    used: int = 0
    daily_limit: int = _DAILY_LIMIT

    def can_call(self) -> bool:
        return self.used < self.daily_limit


class LawKRClient:
    """법제처 API 클라이언트. 호출 결과를 캐시 파일에 누적."""

    def __init__(self, cache_path: Path | None = None, timeout: float = 5.0,
                 daily_limit: int = _DAILY_LIMIT):
        self.cache_path = cache_path or _DEFAULT_CACHE
        self.timeout = timeout
        self.quota = APIQuota(daily_limit=daily_limit)
        self._cache = self._load_cache()

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _call(self, law_name: str) -> dict[str, Any] | None:
        url = _BASE_URL + "?" + urlencode({
            "target": "law",
            "query": law_name,
            "type": "JSON",
        })
        req = Request(url, headers={"User-Agent": "improver-mcp/0.1"})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None
        time.sleep(_SLEEP_BETWEEN)
        return payload

    def lookup(self, law_name: str) -> dict[str, Any] | None:
        if law_name in self._cache:
            return self._cache[law_name]
        if not self.quota.can_call():
            return None
        payload = self._call(law_name)
        if payload is None:
            return None
        self.quota.used += 1  # _call이 mock일 수 있어 여기서 카운트
        self._cache[law_name] = payload
        self._save_cache()
        return payload

    def check_article(self, law_name: str, article_num: str) -> ArticleExistence:
        payload = self.lookup(law_name)
        if payload is None:
            return ArticleExistence(exists=False, status="unknown",
                                    note="법제처 API 호출 실패 또는 일일 한도 초과")
        # 법제처 응답 구조 (LawSearch.LawList): 0건이면 미존재
        law_list = payload.get("LawSearch", {}).get("law")
        if not law_list:
            return ArticleExistence(
                exists=False, status="not_found",
                current_law_name=None, note="법제처에서 매칭 법령 없음"
            )
        # 첫 매칭의 현재명만 반환 (조문 수준 확인은 본문 API 별도 필요)
        first = law_list[0] if isinstance(law_list, list) else law_list
        return ArticleExistence(
            exists=True, status="exists",
            current_law_name=first.get("법령명한글") or law_name,
            note="법제처 API 조회 — 조문 존재는 별도 본문 호출 필요",
        )
