"""LLM 클라이언트 추상화.

기본은 Anthropic Claude (claude-sonnet-4-6, 비용/품질 균형 — 설계서 §4.3).
ANTHROPIC_API_KEY가 없으면 자동으로 MockClient로 fallback해 테스트 가능.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LLMResponse:
    raw: str
    parsed: dict[str, Any] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLMClient(Protocol):
    def call(self, *, system: str, user: str) -> LLMResponse: ...


class MockClient:
    """API 키 없을 때 또는 테스트용. 등록된 응답을 그대로 반환."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None,
                 default: dict[str, Any] | None = None):
        self._responses = responses or {}
        self._default = default
        self.calls: list[tuple[str, str]] = []

    def call(self, *, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        # user 메시지에서 finding_id를 추출해 매칭하거나 default 반환
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

    def call(self, *, system: str, user: str) -> LLMResponse:  # pragma: no cover (API)
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
        return LLMResponse(
            raw=raw,
            parsed=parsed,
            input_tokens=getattr(message.usage, "input_tokens", 0),
            output_tokens=getattr(message.usage, "output_tokens", 0),
            model=self.model,
        )


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
