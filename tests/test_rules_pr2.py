"""PR #2에서 추가된 12개 룰의 단위 테스트."""
from engine.parser import parse_law
from engine.rules import (
    E02Form,
    E03Analog,
    E04Differential,
    E05Sanction,
    F01Rights,
    F02Immunity,
    F03Disposition,
    F04Deemed,
    G01Exception,
    G02Permit,
    S01Insertion,
    S04Enumeration,
)


def _law(text: str, name: str = "테스트법", category: str = "일반"):
    return parse_law(text, name=name, law_category=category)


# ── S-01 ─────────────────────────────────────────────────────────────────────


def test_s01_insertion_ratio_caution():
    # 5개 중 1개 삽입조 = 20% → 주의
    text = "\n\n".join(
        ["제1조(가) 본문.", "제2조(나) 본문.", "제3조(다) 본문.", "제4조(라) 본문.", "제4조의2(삽입) 본문."]
    )
    findings = S01Insertion().scan(_law(text))
    assert findings and findings[0].severity == "주의"


def test_s01_deep_inserted_critical():
    text = "제10조의2의3의4(깊은삽입) 본문."
    findings = S01Insertion().scan(_law(text))
    # 100% 비율 → 심각 (법령 단위) + depth 3 개별 → 심각
    assert any(f.severity == "심각" for f in findings)


# ── S-04 ─────────────────────────────────────────────────────────────────────


def test_s04_enumeration_warning():
    # SLM gate filters most GENERAL+UNKNOWN combos; use adversarial type
    # by giving title that triggers DISPOSITION recognition.
    items = "\n".join(f"  {i}. 항목{i}" for i in range(1, 21))
    text = (
        f"제5조(목록) 장관은 다음 각 호의 어느 하나에 해당하면 허가를 취소할 수 있다.\n"
        f"① 다음 각 호의 사항.\n{items}\n"
    )
    findings = S04Enumeration().scan(_law(text))
    assert findings and findings[0].severity == "경고"


# ── F-01 ─────────────────────────────────────────────────────────────────────


def test_f01_strong_no_remedy_critical():
    text = "제10조(권리) 누구든지 이용자에게 부정한 방법으로 신청해서는 아니 된다."
    findings = F01Rights().scan(_law(text))
    assert findings and findings[0].severity == "심각"


def test_f01_strong_with_remedy_warning():
    text = (
        "제10조(권리) 누구든지 국민에게 부정한 방법으로 신청해서는 아니 된다.\n\n"
        "제11조(이의) 처분에 이의신청을 할 수 있다.\n"
    )
    findings = F01Rights().scan(_law(text))
    target = [f for f in findings if f.article_number == "제10조"]
    assert target and target[0].severity == "경고"


# ── F-02 ─────────────────────────────────────────────────────────────────────


def test_f02_full_immunity_critical():
    text = "제10조(면책) 운영자는 일체의 책임을 지지 아니한다."
    findings = F02Immunity().scan(_law(text))
    assert findings and findings[0].severity == "심각"


def test_f02_partial_with_strong_exception_skipped():
    # LLM 정답 기준 (docs/ENGINE_PRINCIPLES.md R1):
    # "중과실"까지 명시적으로 보호되는 면책은 정상 입법 → 발화 안 함.
    text = "제10조(면책) 운영자는 책임을 지지 아니한다. 다만, 고의 또는 중과실은 제외한다."
    findings = F02Immunity().scan(_law(text))
    assert findings == []


def test_f02_partial_with_weak_exception_caution():
    # "고의·과실"만 예외이고 "중과실" 명시 누락 → 발화 (주의).
    # LLM TP 패턴: F-02-001@국가인권위원회법 류
    text = "제10조(면책) 운영자는 책임을 지지 아니한다. 다만, 고의 또는 과실은 제외한다."
    findings = F02Immunity().scan(_law(text))
    assert findings and findings[0].severity == "주의"


# ── F-03 ─────────────────────────────────────────────────────────────────────


def test_f03_strong_disposition_no_hearing_critical():
    text = "제10조(처분) 장관은 영업정지를 명할 수 있다."
    findings = F03Disposition().scan(_law(text))
    assert findings and findings[0].severity == "심각"


def test_f03_strong_with_hearing_warning():
    text = (
        "제10조(처분) 장관은 영업정지를 명할 수 있다.\n\n"
        "제20조(청문) 처분 전에 청문을 실시하여야 한다.\n"
    )
    findings = F03Disposition().scan(_law(text))
    target = [f for f in findings if f.article_number == "제10조"]
    assert target and target[0].severity == "경고"


# ── F-04 ─────────────────────────────────────────────────────────────────────


def test_f04_deemed_no_notice_critical():
    text = "제10조(동의의제) 신청인이 30일 이내 회신하지 아니하면 동의한 것으로 본다."
    findings = F04Deemed().scan(_law(text))
    assert findings and findings[0].severity == "심각"


def test_f04_deemed_short_period_critical():
    text = (
        "제10조(동의의제) 통지하여야 한다. 5일 이내 회신하지 아니하면 동의한 것으로 본다. "
        "철회할 수 있다."
    )
    findings = F04Deemed().scan(_law(text))
    assert findings and findings[0].severity == "심각"


# ── G-01 ─────────────────────────────────────────────────────────────────────


def test_g01_three_danseo_critical():
    text = (
        "제10조(예외) 본칙. 다만, 첫 단서. 다만, 두 번째 단서. 다만, 세 번째 단서."
    )
    findings = G01Exception().scan(_law(text))
    assert findings and findings[0].severity == "경고"


# ── G-02 ─────────────────────────────────────────────────────────────────────


def test_g02_no_deadline_warning():
    text = "제10조(인허가) 사업자는 장관의 허가를 받아야 한다."
    findings = G02Permit().scan(_law(text))
    assert findings and findings[0].severity == "경고"


def test_g02_multiple_procs_critical():
    text = "제10조(인허가) 사업자는 장관의 인가를 받고, 허가를 받으며, 등록을 하여야 한다."
    findings = G02Permit().scan(_law(text))
    assert findings and findings[0].severity == "심각"


# ── E-02 ─────────────────────────────────────────────────────────────────────


def test_e02_many_forms_warning():
    body = " ".join(f"별지 제{i}호" for i in range(1, 12))
    text = f"제10조(서식) {body}에 따른 서식을 사용한다."
    findings = E02Form().scan(_law(text))
    assert findings and findings[0].severity == "경고"


# ── E-03 ─────────────────────────────────────────────────────────────────────


def test_e03_paper_only_critical():
    text = "제10조(신청) 신청은 서면으로 한다."
    findings = E03Analog().scan(_law(text))
    assert findings and findings[0].severity == "심각"


def test_e03_paper_with_digital_warning():
    text = "제10조(신청) 신청은 서면으로 한다. 다만, 전자적 방법으로도 할 수 있다."
    findings = E03Analog().scan(_law(text))
    assert findings and findings[0].severity == "경고"


# ── E-04 ─────────────────────────────────────────────────────────────────────


def test_e04_differential_registered_law():
    text = (
        "제1조(목적). 제2조 공기업·준정부기관·기타공공기관·시장형·준시장형·위탁집행형·기금관리형."
    )
    findings = E04Differential().scan(_law(text, name="공공기관의 운영에 관한 법률"))
    assert findings and findings[0].severity == "심각"


def test_e04_skips_unregistered_law():
    text = "제1조 본문."
    findings = E04Differential().scan(_law(text, name="미등록법"))
    assert findings == []


# ── E-05 ─────────────────────────────────────────────────────────────────────


def test_e05_sanction_gap_warning():
    text = (
        "제10조(의무) 사업자는 안전기준을 준수하여야 한다.\n\n"
        "제99조(벌칙) 제5조를 위반한 자는 벌금에 처한다.\n"
    )
    findings = E05Sanction().scan(_law(text))
    assert findings and findings[0].severity == "경고"


def test_e05_exhort_excluded():
    text = "제10조(의무) 국가는 진흥을 위하여 노력하여야 한다."
    findings = E05Sanction().scan(_law(text))
    assert findings == []
