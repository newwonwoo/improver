"""S5 억제 지표 도구 — 불변식 검증(작은 샘플)."""
from scripts.measure_suppression import measure


def test_metric_invariants():
    m = measure(5)
    for k in ("baseline_fired_no_filter", "fired_with_filter",
              "suppressed_true_FP_candidates", "suppression_rate_pct"):
        assert k in m
    # 억제는 baseline 이하, 필터 적용 발생도 baseline 이하
    assert m["suppressed_true_FP_candidates"] <= m["baseline_fired_no_filter"]
    assert m["fired_with_filter"] <= m["baseline_fired_no_filter"]
    assert 0.0 <= m["suppression_rate_pct"] <= 100.0
