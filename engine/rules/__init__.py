"""8개 룰 패턴 (Phase 1 PR #1).

S-02 위임검증(단계1), S-03 모호표현, F-05 자의적재량(룰 부분),
G-03 감독, G-04 내부통제, G-05 보고, E-01 조건중첩, L-01 인용법령
"""
from __future__ import annotations

from ..schema import Article, Finding, Law
from .base import PatternResult, Rule
from .e01_conditions import E01Conditions
from .f05_discretion import F05Discretion
from .g03_supervision import G03Supervision
from .g04_internal import G04InternalControl
from .g05_report import G05Report
from .l01_citation import L01Citation
from .s02_delegation import S02Delegation
from .s03_vague import S03Vague


ALL_RULES: list[Rule] = [
    S02Delegation(),
    S03Vague(),
    F05Discretion(),
    L01Citation(),
    G03Supervision(),
    G04InternalControl(),
    G05Report(),
    E01Conditions(),
]


def run_all(law: Law) -> list[Finding]:
    findings: list[Finding] = []
    for rule in ALL_RULES:
        findings.extend(rule.scan(law))
    return findings


__all__ = ["ALL_RULES", "PatternResult", "Rule", "run_all"]
