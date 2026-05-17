"""평가 스크립트 동작 확인 (합성 fixture + 합성 골드셋)."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_evaluate_runs_on_synthetic_goldset(tmp_path):
    goldset = {
        "schema": {"label_values": ["TP", "FP", "BORDER"]},
        "law_files": {"주택도시기금법": "synthetic_housing_fund.txt"},
        "items": [
            {"law": "주택도시기금법", "article": "제22조", "pattern_id": "G-04", "label": "TP"},
            {"law": "주택도시기금법", "article": "제12조", "pattern_id": "G-03", "label": "TP"},
            {"law": "주택도시기금법", "article": "제999조", "pattern_id": "G-04", "label": "TP"},
            {"law": "주택도시기금법", "article": "제2조", "pattern_id": "S-03", "label": "FP"},
        ],
    }
    gs_path = tmp_path / "gs.json"
    gs_path.write_text(json.dumps(goldset, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "evaluate.py"),
            "--goldset",
            str(gs_path),
            "--laws-dir",
            str(REPO / "fixtures"),
            "--report",
            str(out_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert "overall" in payload
    by_pattern = {row["pattern_id"]: row for row in payload["per_pattern"]}
    # G-04 — 제22조 정탐 + 제999조 미탐
    assert by_pattern["G-04"]["tp"] == 1
    assert by_pattern["G-04"]["missed_tp"] == 1
    # G-03 — 제12조 정탐
    assert by_pattern["G-03"]["tp"] == 1
    # S-03 — 제2조 FP를 엔진이 잘 걸렀으면 correctly_filtered_fp = 1
    assert by_pattern["S-03"]["correctly_filtered_fp"] == 1
