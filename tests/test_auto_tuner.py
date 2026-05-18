"""auto_tuner 단위 테스트."""
import json
from pathlib import Path

from engine.auto_tuner import auto_tune


def _write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_strong_negative_delta_triggers_threshold_loosening(tmp_path):
    prop = tmp_path / "proposals.json"
    pat = tmp_path / "patterns.json"
    _write(prop, {
        "threshold_proposals": [
            {"pattern_id": "S-01", "avg_delta": -1.6, "n": 50, "action": "x"}
        ],
        "fp_filter_proposals": [],
    })
    _write(pat, {"S-01": {"enabled": True,
                            "thresholds": {"심각": 40, "경고": 30}}})
    r = auto_tune(proposals_path=prop, patterns_config_path=pat)
    assert len(r.threshold_changes) == 1
    after = json.loads(pat.read_text(encoding="utf-8"))
    assert after["S-01"]["thresholds"]["심각"] > 40
    assert r.backup_path  # 백업 생성됨


def test_weak_delta_skipped_for_review(tmp_path):
    prop = tmp_path / "proposals.json"
    pat = tmp_path / "patterns.json"
    _write(prop, {
        "threshold_proposals": [
            {"pattern_id": "S-01", "avg_delta": -0.8, "n": 50, "action": "x"},  # |delta|<1
            {"pattern_id": "S-02", "avg_delta": -1.5, "n": 10, "action": "x"},  # n<30
        ],
        "fp_filter_proposals": [],
    })
    _write(pat, {})
    r = auto_tune(proposals_path=prop, patterns_config_path=pat)
    assert r.threshold_changes == []
    assert len(r.skipped_for_review) == 2


def test_positive_delta_not_auto_applied(tmp_path):
    prop = tmp_path / "proposals.json"
    pat = tmp_path / "patterns.json"
    _write(prop, {
        "threshold_proposals": [
            {"pattern_id": "S-01", "avg_delta": 1.5, "n": 50, "action": "x"}
        ],
        "fp_filter_proposals": [],
    })
    _write(pat, {"S-01": {"enabled": True, "thresholds": {"심각": 40}}})
    r = auto_tune(proposals_path=prop, patterns_config_path=pat)
    assert r.threshold_changes == []
    # 사람 검토로 미룬 것에 포함
    assert any(s["pattern_id"] == "S-01" for s in r.skipped_for_review)


def test_strong_fp_rate_adds_warning_flag(tmp_path):
    prop = tmp_path / "proposals.json"
    pat = tmp_path / "patterns.json"
    _write(prop, {
        "threshold_proposals": [],
        "fp_filter_proposals": [
            {"pattern_id": "G-04", "fp_rate": 0.7, "n": 50, "top_reasons": []}
        ],
    })
    _write(pat, {})
    r = auto_tune(proposals_path=prop, patterns_config_path=pat)
    assert len(r.fp_filter_changes) == 1
    after = json.loads(pat.read_text(encoding="utf-8"))
    assert "fp_warning" in after["G-04"]


def test_dry_run_does_not_write(tmp_path):
    prop = tmp_path / "proposals.json"
    pat = tmp_path / "patterns.json"
    _write(prop, {
        "threshold_proposals": [
            {"pattern_id": "S-01", "avg_delta": -1.6, "n": 50}
        ],
        "fp_filter_proposals": [],
    })
    _write(pat, {"S-01": {"enabled": True, "thresholds": {"심각": 40}}})
    before = pat.read_text(encoding="utf-8")
    r = auto_tune(proposals_path=prop, patterns_config_path=pat, dry_run=True)
    assert r.threshold_changes  # 변경은 잡혀있음
    assert pat.read_text(encoding="utf-8") == before  # 파일 그대로
