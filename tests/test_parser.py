from pathlib import Path

from engine.parser import parse_law


FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_housing_fund.txt"


def test_parse_housing_fund_articles():
    text = FIXTURE.read_text(encoding="utf-8")
    law = parse_law(text, name="주택도시기금법", law_category="공공기관법")
    # fixture에는 17개 조문이 있음 (제1,2,3,5,6,7,9,10,12,13,14,15,22,25,26,32,34의2)
    assert len(law.articles) == 17
    nums = [a.number for a in law.articles]
    assert "제10조" in nums
    assert "제34조의2" in nums


def test_parse_inserted_article_depth():
    text = "제10조(본조) 본문.\n\n제10조의2(삽입조) 추가 본문.\n"
    law = parse_law(text, name="테스트법")
    by_num = {a.number: a for a in law.articles}
    assert by_num["제10조"].insert_depth == 0
    assert by_num["제10조의2"].insert_depth == 1
    assert by_num["제10조의2"].is_inserted is True


def test_parse_paragraph_and_item():
    text = (
        "제5조(목록)\n"
        "① 다음 각 호의 사항을 정한다.\n"
        "  1. 첫 번째 항목\n"
        "  2. 두 번째 항목\n"
        "  3. 세 번째 항목\n"
        "② 추가 사항을 정한다.\n"
    )
    law = parse_law(text, name="테스트법")
    art = law.articles[0]
    assert len(art.paragraphs) == 2
    assert art.paragraphs[0].number == "①"
    assert len(art.paragraphs[0].items) == 3


def test_definition_article_detection():
    text = (
        "제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.\n"
        "  1. 정의1\n"
    )
    law = parse_law(text, name="테스트법")
    assert law.articles[0].is_definition()


def test_addendum_stripped():
    text = (
        "제1조(목적) 본문.\n\n"
        "부 칙\n"
        "제1조(시행일) 이 법은 공포일부터 시행한다.\n"
    )
    law = parse_law(text, name="테스트법")
    assert len(law.articles) == 1
    assert law.articles[0].number == "제1조"
