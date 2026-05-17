"""LLM 진단 엔진 (엔진 설계서 §4).

PR #3: 3패턴(F-04/F-05/E-05) 정밀 판단 + 권고안 Layer 3.
- client: Anthropic SDK 추상화 + Mock 클라이언트 (API 키 없을 때 fallback)
- prompts: 시스템 프롬프트 3종 + 권고안 프롬프트
- judge: 룰 후보 → LLM 등급 조정
- recommender_layer3: 심각·경고 finding에 맞춤 권고안 생성
"""
from .client import LLMClient, LLMResponse, MockClient, AnthropicClient
from .judge import judge_findings
from .recommender_layer3 import generate_recommendations

__all__ = [
    "AnthropicClient",
    "LLMClient",
    "LLMResponse",
    "MockClient",
    "generate_recommendations",
    "judge_findings",
]
