from engine.parser import parse_law
from engine.rules import (
    E01Conditions,
    F05Discretion,
    G03Supervision,
    G04InternalControl,
    G05Report,
    L01Citation,
    S02Delegation,
    S03Vague,
)


def _law(text: str, name: str = "테스트법", category: str = "일반"):
    return parse_law(text, name=name, law_category=category)


def test_s03_vague_obligation_two_keywords_severe():
    law = _law("제10조(의무) 장관은 합리적인 이유 없이 필요하다고 인정하는 경우 조치를 하여야 한다.")
    findings = S03Vague().scan(law)
    assert len(findings) == 1
    assert findings[0].severity == "심각"


def test_s03_definition_article_excluded():
    text = (
        "제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.\n"
        "  1. '그 밖의 사항'이란 추가 사항을 말한다.\n"
    )
    findings = S03Vague().scan(_law(text))
    assert findings == []


def test_f05_discretion_administrative_subject():
    text = (
        "제9조(운용변경) 국토교통부장관은 필요하다고 인정하는 경우에는 "
        "사업자의 허가를 취소할 수 있다.\n"
    )
    findings = F05Discretion().scan(_law(text))
    assert len(findings) == 1
    assert findings[0].severity == "심각"


def test_f05_benefit_excluded():
    text = "제9조(지원) 장관은 필요하다고 인정하는 경우 지원을 할 수 있다."
    findings = F05Discretion().scan(_law(text))
    assert findings == []  # 수익적 재량 제외


def test_g03_supervision_all_missing():
    text = "제12조(감독) 국토교통부장관은 기금의 운용을 감독한다."
    findings = G03Supervision().scan(_law(text))
    assert len(findings) == 1
    assert findings[0].severity == "심각"
    assert "감독 범위" in findings[0].summary


def test_g04_internal_control_only_applicable_laws():
    # 적용 가능 법령(기금·공단·금융 등)이라도 본문에 진성 내부통제 신호가
    # 없으면 G-04 미발화 (docs/ENGINE_PRINCIPLES.md R1: 단일 키워드 발화 금지).
    # LLM 검증 기준: G-04 적용 조건 = 법령명 화이트리스트 AND 본문에 진성 신호.
    bare = "\n\n".join(f"제{i}조(사항{i}) 본문{i}." for i in range(1, 8))
    assert G04InternalControl().scan(_law(bare, name="일반법")) == []
    # 적용 후보 법령이지만 진성 신호 없음 → 미발화 (LLM 정답 기준)
    assert G04InternalControl().scan(_law(bare, name="주택도시기금법")) == []
    # 진성 신호(준법감시인 — 5요소엔 없지만 명시적 내부통제 키워드) 1개만 있는 경우:
    # 5요소 0/5 + explicit 신호 존재 → 심각으로 발화
    with_signal = bare + "\n\n제8조(준법) 준법감시인은 두지 아니한다."
    findings = G04InternalControl().scan(_law(with_signal, name="주택도시기금법"))
    assert len(findings) == 1
    assert findings[0].severity == "심각"


def test_g05_report_missing_elements():
    text = "제14조(보고) 수탁기관은 운영상황을 보고하여야 한다."
    findings = G05Report().scan(_law(text))
    assert len(findings) == 1
    assert findings[0].severity == "경고"


def test_l01_citation_overflow():
    laws = "「" + "법」, 「".join(
        ["가법", "나법", "다법", "라법", "마법", "바법", "사법"]
    ) + "법」"
    text = f"제9조(인용) 이 조문은 {laws}에 따른다."
    findings = L01Citation().scan(_law(text))
    assert len(findings) == 1


def test_e01_condition_nesting():
    text = (
        "제7조(요건) 다음 각 호의 요건을 모두 충족하고 또한 기준을 갖추어야 하며 "
        "필요한 경우에 해당하는 경우로서 추가 요건을 충족하는 경우에 적용한다."
    )
    findings = E01Conditions().scan(_law(text))
    assert findings and findings[0].severity in {"경고", "심각", "주의"}


def test_s02_delegation_vague_scope_caution():
    text = "제15조(위임) 그 밖에 필요한 사항은 대통령령으로 정한다."
    findings = S02Delegation().scan(_law(text))
    assert len(findings) == 1
    assert findings[0].severity == "경고"
