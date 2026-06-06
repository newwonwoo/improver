"""evaluate_cv (V1 평가 신뢰성) 스모크 테스트.

- _fit_eval_once / _counts_from_preds / _prf 헬퍼의 계약 검증 (torch 불필요한 순수 부분).
- evaluate_cv 는 torch 있을 때만: 작은 합성 데이터로 구조/CI 단조성만 확인,
  프로덕션 모델 파일을 건드리지 않음을 검증.
"""
import importlib

import numpy as np
import pytest

mod = importlib.import_module("engine.slm.torch_brain")


def test_prf_basic():
    # tp=2, fp=1, fn=1 → P=2/3, R=2/3, F1=2/3
    p, r, f1 = mod._prf(2, 1, 1)
    assert abs(p - 2 / 3) < 1e-9
    assert abs(r - 2 / 3) < 1e-9
    assert abs(f1 - 2 / 3) < 1e-9
    # 전부 0 이면 0 (0 분모 가드)
    assert mod._prf(0, 0, 0) == (0.0, 0.0, 0.0)


def test_counts_from_preds_masks_missing():
    # 2 카테고리만 채우고 라벨 -1(결측) 마스킹 확인
    from engine.slm.brain import CATEGORIES
    ncat = len(CATEGORIES)
    pred = np.zeros((3, ncat), dtype=np.float32)
    y = np.full((3, ncat), -1.0, dtype=np.float32)
    # cat0: pred [0.9,0.1,0.9], true [1,1,0] → tp=1, fn=1, fp=1
    pred[:, 0] = [0.9, 0.1, 0.9]
    y[:, 0] = [1, 1, 0]
    c = mod._counts_from_preds(pred, y)
    cat0 = c[CATEGORIES[0]]
    assert (cat0["tp"], cat0["fn"], cat0["fp"]) == (1, 1, 1)
    # 결측(-1) 카테고리는 카운트 0
    cat1 = c[CATEGORIES[1]]
    assert cat1["tp"] == cat1["fp"] == cat1["fn"] == cat1["tn"] == 0


@pytest.mark.skipif(not mod._TORCH_OK, reason="torch 미설치")
def test_evaluate_cv_does_not_touch_production_model(monkeypatch, tmp_path):
    """evaluate_cv 는 임시 모델만 쓰고 outputs/slm_torch_model.pt 를 저장하지 않는다."""
    from engine.slm.brain import CATEGORIES
    ncat = len(CATEGORIES)
    n = 120
    rng = np.random.default_rng(0)
    dense = rng.standard_normal((n, 4)).astype(np.float32)
    ti = np.zeros(n, dtype=np.int64)
    si = np.zeros(n, dtype=np.int64)
    mi = np.zeros(n, dtype=np.int64)
    # 카테고리 0,1 에 충분한 양성(>=15), 나머지는 결측(-1)
    y = np.full((n, ncat), -1.0, dtype=np.float32)
    y[:, 0] = (rng.random(n) < 0.4).astype(np.float32)
    y[:, 1] = (rng.random(n) < 0.4).astype(np.float32)

    monkeypatch.setattr(mod, "collect_torch_data", lambda: (dense, ti, si, mi, y))

    saved = {"called": False}
    real_save = mod.torch.save
    monkeypatch.setattr(mod.torch, "save", lambda *a, **k: saved.__setitem__("called", True))

    res = mod.evaluate_cv(k=3, seed=1, n_boot=50, epochs=3)

    # 저장 호출 없음
    assert saved["called"] is False
    # 구조 검증
    assert set(res["per_cat"]) == set(CATEGORIES)
    assert "ci_lo" in res["total"] and "ci_hi" in res["total"]
    # CI 단조성 (lo <= point <= hi) — 측정가능 카테고리
    t = res["total"]
    assert t["ci_lo"] <= t["f1"] + 1e-6
    assert t["f1"] <= t["ci_hi"] + 1e-6
    # 측정불가 플래그: 결측 카테고리는 n_pos=0 < 15
    assert res["per_cat"][CATEGORIES[2]]["measurable"] is False
