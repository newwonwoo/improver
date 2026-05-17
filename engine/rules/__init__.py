"""룰 패턴 카탈로그 (PR #2 이후 전 18개).

S-01 삽입조 · S-02 위임 · S-03 모호 · S-04 열거
F-01 권리제한 · F-02 면책 · F-03 처분 · F-04 의제(룰) · F-05 재량(룰)
L-01 인용법령 (L-02/L-03은 mcp 모듈)
G-01 예외단서 · G-02 인허가 · G-03 감독 · G-04 내부통제 · G-05 보고
E-01 조건중첩 · E-02 서식 · E-03 아날로그 · E-04 차등 · E-05 제재공백(룰)
"""
from __future__ import annotations

from ..schema import Article, Finding, Law
from .base import PatternResult, Rule, make_finding
from .e01_conditions import E01Conditions
from .e02_form import E02Form
from .e03_analog import E03Analog
from .e04_differential import E04Differential
from .e05_sanction import E05Sanction
from .f01_rights import F01Rights
from .f02_immunity import F02Immunity
from .f03_disposition import F03Disposition
from .f04_deemed import F04Deemed
from .f05_discretion import F05Discretion
from .g01_exception import G01Exception
from .g02_permit import G02Permit
from .g03_supervision import G03Supervision
from .g04_internal import G04InternalControl
from .g05_report import G05Report
from .l01_citation import L01Citation
from .l02_cross_ref import L02CrossRef
from .l03_broken_ref import L03BrokenRef
from .s01_insertion import S01Insertion
from .s02_delegation import S02Delegation
from .s03_vague import S03Vague
from .s04_enumeration import S04Enumeration


ALL_RULES: list[Rule] = [
    S01Insertion(),
    S02Delegation(),
    S03Vague(),
    S04Enumeration(),
    F01Rights(),
    F02Immunity(),
    F03Disposition(),
    F04Deemed(),
    F05Discretion(),
    L01Citation(),
    L02CrossRef(),
    L03BrokenRef(),
    G01Exception(),
    G02Permit(),
    G03Supervision(),
    G04InternalControl(),
    G05Report(),
    E01Conditions(),
    E02Form(),
    E03Analog(),
    E04Differential(),
    E05Sanction(),
]


def run_all(law: Law) -> list[Finding]:
    findings: list[Finding] = []
    for rule in ALL_RULES:
        findings.extend(rule.scan(law))
    return findings


__all__ = [
    "ALL_RULES",
    "PatternResult",
    "Rule",
    "make_finding",
    "run_all",
    "E01Conditions",
    "E02Form",
    "E03Analog",
    "E04Differential",
    "E05Sanction",
    "F01Rights",
    "F02Immunity",
    "F03Disposition",
    "F04Deemed",
    "F05Discretion",
    "G01Exception",
    "G02Permit",
    "G03Supervision",
    "G04InternalControl",
    "G05Report",
    "L01Citation",
    "L02CrossRef",
    "L03BrokenRef",
    "S01Insertion",
    "S02Delegation",
    "S03Vague",
    "S04Enumeration",
]
