"""HTTP API 서버 (FastAPI).

설계서 §6.1 Phase 2 — 독립 웹사이트 배포 준비.
- POST /analyze: 법령 텍스트 + 메타 → AnalysisResult JSON
- GET  /patterns: 사용 가능한 룰 패턴 목록
- GET  /agencies: 서브체크 → 기관 매핑
- GET  /healthz: 헬스 체크

fastapi 미설치 시 ImportError를 raise하므로 import는 lazy.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _detect_category(name: str) -> str:
    if any(k in name for k in ("금융", "은행", "보험", "투자", "신용", "증권")):
        return "금융법"
    if any(k in name for k in ("공공기관", "공기업", "공단", "공사", "기금")):
        return "공공기관법"
    if any(k in name for k in ("민법", "상법", "계약")):
        return "민사법"
    if any(k in name for k in ("소송", "절차", "재판", "심판")):
        return "절차법"
    return "일반"


def create_app(*, use_llm: bool = False):
    """FastAPI 앱 인스턴스 생성."""
    try:
        from fastapi import Body, FastAPI, HTTPException  # noqa: WPS433
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "fastapi/pydantic 미설치. `pip install fastapi pydantic uvicorn`"
        ) from e

    from . import cases, cross_pattern, fpc, recommender, scorer
    from .parser import parse_law
    from .rules import run_all

    app = FastAPI(title="improver", version="0.1.0")
    repo_root = Path(__file__).resolve().parent.parent

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/patterns")
    def patterns() -> dict[str, Any]:
        return {
            "patterns": [
                {"id": r.pattern_id, "name": r.pattern_name, "category": r.category}
                for r in __import__("engine.rules", fromlist=["ALL_RULES"]).ALL_RULES
            ]
        }

    @app.get("/agencies")
    def agencies() -> dict[str, Any]:
        path = repo_root / "config" / "sub_check_agencies.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @app.post("/analyze")
    def analyze(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        name = payload.get("name", "")
        text = payload.get("text", "")
        law_type = payload.get("law_type", "법률")
        category = payload.get("category") or _detect_category(name)
        use_cross = payload.get("cross_pattern", True)
        if not text.strip():
            raise HTTPException(status_code=400, detail="text가 비어있습니다")
        if not name.strip():
            raise HTTPException(status_code=400, detail="name이 비어있습니다")

        law = parse_law(text, name=name, law_type=law_type, law_category=category)
        findings = fpc.correct(law, run_all(law))
        result = scorer.compute(law, findings)
        result = recommender.apply(result)
        result = cases.attach(result)
        if use_cross:
            result = cross_pattern.annotate(result)
            result = scorer.compute(law, result.findings)
        return result.to_dict()

    return app
