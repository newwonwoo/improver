"""StackBrain 강화 컴포넌트 테스트 — 로드·보정확률·프로덕션 무변."""
import pickle
from pathlib import Path

import pytest

from engine.parser import parse_law
from engine.slm.stack_brain import StackBrain, CATEGORIES

_ART = parse_law(
    "제1조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.\n"
    "제2조(위임) 필요한 사항은 대통령령으로 정한다.",
    name="t",
)
_MODEL = Path("outputs/stack_brain_models.pkl")
_has_model = _MODEL.exists()


def test_categories_constant():
    assert CATEGORIES == ["구조", "공정성", "적법성", "거버넌스", "효율성"]


def test_load_missing_returns_none(tmp_path):
    assert StackBrain.load(str(tmp_path / "nope.pkl")) is None


@pytest.mark.skipif(not _has_model, reason="stack_brain_models.pkl 미존재(학습 전)")
def test_scores_are_calibrated_probabilities():
    brain = StackBrain.load()
    assert brain is not None
    art = _ART.articles[0]
    scores = brain.score_article(art)
    assert set(scores).issubset(set(CATEGORIES))
    for cat, p in scores.items():
        assert 0.0 <= p <= 1.0, f"{cat} 확률 범위 위반: {p}"


@pytest.mark.skipif(not _has_model, reason="stack_brain_models.pkl 미존재(학습 전)")
def test_diagnose_includes_cv_f1_and_threshold():
    brain = StackBrain.load()
    diag = brain.diagnose_article(_ART.articles[0])
    for cat, d in diag.items():
        assert "proba" in d and "is_defect" in d
        assert "cv_f1" in d and 0.0 <= d["cv_f1"] <= 1.0
        assert d["is_defect"] == (d["proba"] >= d["threshold"])


def test_production_path_does_not_import_stack_brain():
    """기본 엔진 경로(report template)는 StackBrain 을 쓰지 않는다(opt-in)."""
    tmpl = Path("engine/report/template.py").read_text(encoding="utf-8")
    assert "stack_brain" not in tmpl and "StackBrain" not in tmpl


@pytest.mark.skipif(not _has_model, reason="stack_brain_models.pkl 미존재")
def test_artifact_has_expected_structure():
    with open(_MODEL, "rb") as f:
        stacks = pickle.load(f)
    assert len(stacks) >= 4               # 표본 충분한 카테고리들
    for cat, st in stacks.items():
        assert hasattr(st, "meta") and hasattr(st, "calibrator")
        assert hasattr(st, "base_text") and hasattr(st, "cv_f1")
