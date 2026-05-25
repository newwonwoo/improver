"""논리 추론 계층 — 신경망 신호를 법적 논리 흐름으로 연결 (neuro-symbolic)."""
from .inference import (
    ReasoningStep,
    ReasoningResult,
    InferenceRule,
    Premise,
    KNOWLEDGE_BASE,
    reason_over,
    diagnose_with_reasoning,
)

__all__ = [
    "ReasoningStep",
    "ReasoningResult",
    "InferenceRule",
    "Premise",
    "KNOWLEDGE_BASE",
    "reason_over",
    "diagnose_with_reasoning",
]
