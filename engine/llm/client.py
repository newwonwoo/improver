"""LLM 클라이언트 추상화.

기본은 Anthropic Claude (claude-sonnet-4-6, 비용/품질 균형 — 설계서 §4.3).
ANTHROPIC_API_KEY가 없으면 자동으로 MockClient로 fallback해 테스트 가능.
설계서 §4.5: 모든 호출의 입출력은 LLMCallLog로 보존.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


@dataclass
class LLMResponse:
    raw: str
    parsed: dict[str, Any] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


@dataclass
class LLMCallLog:
    timestamp: str
    model: str
    system_hash: str
    user: str
    raw_response: str
    parsed: dict[str, Any] | None
    input_tokens: int
    output_tokens: int
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "model": self.model,
            "system_hash": self.system_hash,
            "user": self.user,
            "raw_response": self.raw_response,
            "parsed": self.parsed,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
        }


class LLMClient(Protocol):
    log: list[LLMCallLog]

    def call(self, *, system: str, user: str) -> LLMResponse: ...


def _hash_system(system: str) -> str:
    return hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MockClient:
    """API 키 없을 때 또는 테스트용. 등록된 응답을 그대로 반환."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None,
                 default: dict[str, Any] | None = None):
        self._responses = responses or {}
        self._default = default
        self.calls: list[tuple[str, str]] = []
        self.log: list[LLMCallLog] = []

    def call(self, *, system: str, user: str) -> LLMResponse:
        start = time.monotonic()
        self.calls.append((system, user))
        payload: dict[str, Any] | None = None
        for key, resp in self._responses.items():
            if key in user:
                payload = resp
                break
        if payload is None:
            payload = self._default
        if payload is None:
            raise RuntimeError("MockClient: matching response not registered.")
        raw = json.dumps(payload, ensure_ascii=False)
        duration_ms = int((time.monotonic() - start) * 1000)
        self.log.append(LLMCallLog(
            timestamp=_now(),
            model="mock",
            system_hash=_hash_system(system),
            user=user,
            raw_response=raw,
            parsed=payload,
            input_tokens=0,
            output_tokens=0,
            duration_ms=duration_ms,
        ))
        return LLMResponse(raw=raw, parsed=payload, model="mock")


class AnthropicClient:
    """Anthropic SDK 호출 래퍼. anthropic 미설치 시 RuntimeError."""

    def __init__(self, model: str = "claude-sonnet-4-6",
                 max_tokens: int = 1024, timeout: float = 30.0):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "anthropic 패키지가 설치되지 않았습니다. "
                "`pip install anthropic` 후 ANTHROPIC_API_KEY 환경변수 설정 필요."
            ) from e
        from anthropic import Anthropic  # noqa: WPS433

        self._client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.log: list[LLMCallLog] = []

    def call(self, *, system: str, user: str) -> LLMResponse:  # pragma: no cover (API)
        start = time.monotonic()
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=self.timeout,
        )
        raw = "".join(block.text for block in message.content if hasattr(block, "text"))
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            pass
        duration_ms = int((time.monotonic() - start) * 1000)
        input_tokens = getattr(message.usage, "input_tokens", 0)
        output_tokens = getattr(message.usage, "output_tokens", 0)
        self.log.append(LLMCallLog(
            timestamp=_now(),
            model=self.model,
            system_hash=_hash_system(system),
            user=user,
            raw_response=raw,
            parsed=parsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
        ))
        return LLMResponse(
            raw=raw,
            parsed=parsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self.model,
        )


def dump_log(client: LLMClient, path: Path) -> int:
    """LLMCallLog 목록을 JSONL로 저장. 반환: 저장 건수."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for entry in client.log:
            fp.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    return len(client.log)


def make_default_client() -> LLMClient:
    """환경 변수에 따라 Anthropic 또는 Mock."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicClient()
        except RuntimeError:
            pass
    return MockClient(default={
        "severity": "경고",
        "severity_basis": "Mock 응답 (API 키 또는 anthropic 패키지 없음).",
        "reasoning": "LLM 진단 미수행 — 룰 등급 유지를 권장합니다.",
    })
