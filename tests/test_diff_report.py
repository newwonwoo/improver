"""강화 전/후 비교 리포트 테스트."""
import json
from pathlib import Path

from engine.diff_report import compare


def _write_result(d: Path, name: str, *, grade: str, score: float,
                   findings: list[dict]):
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "law": {"law_id": "x", "name": name, "type": "법률",
                "law_category": "일반", "articles": []},
        "findings": findings,
        "article_scores": [], "category_scores": {},
        "law_score": score, "law_grade": grade,
        "engine_version": "0.1.0",
    }
    (d / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False),
                                      encoding="utf-8")


def _finding(fid: str, pid: str, sev: str = "심각",
              fp: bool = False, layer: int | None = None) -> dict:
    rec = {"template": "x"}
    if layer is not None:
        rec["layer"] = layer
    return {
        "finding_id": fid, "pattern_id": pid, "pattern_name": pid,
        "category": "거버넌스", "article_id": "art_1", "article_number": "제1조",
        "matched_text": "x", "severity": sev, "severity_score": 10,
        "summary": "x", "detection_method": "rule", "fix_type": None,
        "recommendation": rec, "is_false_positive": fp,
        "false_positive_reason": None,
    }


def test_compare_grade_transitions(tmp_path):
    b = tmp_path / "before"
    a = tmp_path / "after"
    _write_result(b, "법령A", grade="F", score=200, findings=[_finding("x", "G-04")])
    _write_result(a, "법령A", grade="D", score=70, findings=[
        _finding("x", "G-04", fp=True),
    ])
    r = compare(b, a)
    assert r["common_laws"] == 1
    assert r["grade_transitions"].get("F→D") == 1
    assert r["fp_count_before"] == 0
    assert r["fp_count_after"] == 1
    assert r["avg_score_delta"] == -130.0


def test_compare_layer3_growth(tmp_path):
    b = tmp_path / "b"; a = tmp_path / "a"
    _write_result(b, "법령X", grade="F", score=100, findings=[_finding("x", "G-04")])
    _write_result(a, "법령X", grade="F", score=100, findings=[
        _finding("x", "G-04", layer=3)
    ])
    r = compare(b, a)
    assert r["layer3_before"] == 0
    assert r["layer3_after"] == 1


def test_compare_handles_disjoint_law_sets(tmp_path):
    b = tmp_path / "b"; a = tmp_path / "a"
    _write_result(b, "A", grade="F", score=100, findings=[])
    _write_result(b, "B", grade="D", score=60, findings=[])
    _write_result(a, "A", grade="F", score=100, findings=[])
    _write_result(a, "C", grade="C", score=40, findings=[])
    r = compare(b, a)
    assert r["common_laws"] == 1
    assert r["only_before"] == 1  # B
    assert r["only_after"] == 1   # C


def test_compare_top_changes_sorted_by_abs_delta(tmp_path):
    b = tmp_path / "b"; a = tmp_path / "a"
    _write_result(b, "A", grade="F", score=200, findings=[])
    _write_result(b, "B", grade="F", score=150, findings=[])
    _write_result(a, "A", grade="C", score=50, findings=[])   # delta -150
    _write_result(a, "B", grade="D", score=80, findings=[])   # delta -70
    r = compare(b, a)
    assert r["top_changes"][0]["law"] == "A"
    assert r["top_changes"][0]["delta"] == -150


def test_compare_ignores_summary_files(tmp_path):
    b = tmp_path / "b"; a = tmp_path / "a"
    _write_result(b, "법령A", grade="F", score=100, findings=[])
    _write_result(a, "법령A", grade="F", score=100, findings=[])
    # 요약 파일은 무시되어야
    (b / "batch_summary.json").write_text('{"total_laws": 1}', encoding="utf-8")
    (a / "batch_import_summary.json").write_text('{}', encoding="utf-8")
    r = compare(b, a)
    assert r["common_laws"] == 1
