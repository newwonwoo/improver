from engine.mcp import (
    LawIndex,
    check_article_exists,
    check_enforcement_decree,
    load_default_index,
)


def test_load_default_index_has_housing_fund():
    idx = load_default_index()
    assert idx.find("주택도시기금법") is not None
    assert idx.find("주기법") is not None  # 약칭 매칭


def test_check_article_exists_positive():
    res = check_article_exists("주택도시기금법", "10")
    assert res.exists is True
    assert res.status == "exists"


def test_check_article_exists_not_found():
    res = check_article_exists("주택도시기금법", "999")
    assert res.exists is False
    assert res.status == "not_found"


def test_check_article_exists_repealed():
    res = check_article_exists("주택건설촉진법", "1")
    assert res.status == "law_repealed"
    assert res.current_law_name == "주택법"


def test_check_article_exists_renamed():
    # repealed_laws.json의 제명변경 항목 — 인덱스에 없는 옛 이름이라야 작동
    from engine.mcp import LawIndex, check_article_exists as check_with_idx
    idx = LawIndex(
        laws=[],
        repealed={
            "제명변경": [
                {"old_name": "옛이름법", "new_name": "새이름법", "date": "2020-01-01"}
            ]
        },
    )
    res = check_with_idx("옛이름법", "1", index=idx)
    assert res.status == "law_renamed"
    assert res.current_law_name == "새이름법"


def test_check_article_exists_unknown():
    res = check_article_exists("가공의 법", "1")
    assert res.status == "unknown"


def test_check_enforcement_decree_full():
    res = check_enforcement_decree("주택도시기금법", "10")
    assert res.decree_exists is True
    assert res.decree_name == "주택도시기금법 시행령"
    assert res.coverage == "full"


def test_check_enforcement_decree_no_decree():
    res = check_enforcement_decree("민법", "1")
    assert res.coverage == "none"


def test_check_enforcement_decree_now_resolves_via_real_index():
    """legalize-kr 통합 후 주택법 시행령이 인덱스에 등록되어 매칭됨."""
    res = check_enforcement_decree("주택법", "10")
    assert res.decree_exists is True
    assert res.decree_name == "주택법 시행령"
    assert res.coverage in {"full", "partial"}


def test_law_index_custom_construction():
    idx = LawIndex(
        laws=[
            {"name": "테스트법", "short_names": ["테법"], "article_numbers": ["1", "2"]}
        ]
    )
    assert idx.find("테법")["name"] == "테스트법"
    assert idx.has_article("테스트법", "1").exists is True
    assert idx.has_article("테스트법", "3").exists is False
