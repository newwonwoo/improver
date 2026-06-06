"""REASONING_RULE_CAT: 추론룰→카테고리 매핑이 트레이너 CATEGORIES와 정합한지.

phase13 verdict 라벨(추론룰 R-*)이 학습기에 적재되려면 카테고리 매핑이 필요.
(S2: 라벨→학습기 연결부 — 0행 스킵 버그 방지)
"""
from engine.slm.brain import CATEGORIES
from engine.slm.learn import REASONING_RULE_CAT


def test_reasoning_cats_within_categories():
    for rule, cat in REASONING_RULE_CAT.items():
        assert cat in CATEGORIES, f"{rule}→{cat} 가 CATEGORIES에 없음"


def test_verdict_rules_mapped():
    # 실제 phase13 배치에서 나온 발화룰들은 반드시 매핑돼 있어야 적재됨.
    for rule in ("R-DELEG-BLANKET", "R-NO-DISP-STANDARD", "R-NO-REASON", "R-LAW-PRECEDENCE"):
        assert rule in REASONING_RULE_CAT
