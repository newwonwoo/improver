"""TextBrain(라운드2 텍스트 자산) 테스트 — 분리·회귀0 불변식."""
from pathlib import Path

import pytest

from engine.slm.text_brain import TextBrain

_HAS_MODEL = Path("outputs/text_brain_models.pkl").exists()


def test_load_missing_returns_none():
    assert TextBrain.load("outputs/__no_such_model__.pkl") is None


@pytest.mark.skipif(not _HAS_MODEL, reason="text_brain_models.pkl 미생성")
def test_score_is_probability_dict():
    tb = TextBrain.load()
    assert tb is not None
    scores = tb.score("사업자는 영업을 신고하여야 하며 시장은 과태료를 부과할 수 있다.")
    assert scores
    for cat, p in scores.items():
        assert 0.0 <= p <= 1.0
        assert cat in tb.categories


@pytest.mark.skipif(not _HAS_MODEL, reason="text_brain_models.pkl 미생성")
def test_win_only_subset_of_full():
    tb = TextBrain.load()
    full = tb.score("위원회는 대통령령으로 정하는 바에 따라 심의한다.")
    win = tb.score_win_only("위원회는 대통령령으로 정하는 바에 따라 심의한다.")
    assert set(win).issubset(set(full))
    assert "공정성" not in win          # 공정성은 룰 우세 → 텍스트 비활성


def test_text_brain_does_not_touch_engine_default_path():
    """회귀0 불변식: ensemble_analyze 는 TextBrain 을 import·호출하지 않는다."""
    import inspect
    from engine.slm import ensemble
    src = inspect.getsource(ensemble)
    assert "text_brain" not in src and "TextBrain" not in src
