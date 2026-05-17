"""합성 골드셋이 측정 가능한 정밀도/재현율 임계를 통과하는지 확인.

PR #2~#4 룰을 회귀시키지 않도록, 동일 fixture로 같은 결과가 나오는지 검증.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GOLDSET = REPO / "data" / "goldset" / "synthetic_housing_fund.json"


def test_synthetic_goldset_meets_minimum_precision_recall(tmp_path):
    out = tmp_path / "report.json"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "evaluate.py"),
         "--goldset", str(GOLDSET),
         "--laws-dir", str(REPO / "fixtures"),
         "--report", str(out)],
        check=True, capture_output=True, text=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    overall = payload["overall"]
    assert overall["precision"] is not None
    assert overall["precision"] >= 0.7, f"precision regression: {overall}"
    # 합성 골드셋 9 TP 중 최소 7건 정탐
    assert overall["tp"] >= 7, f"too many missed: {overall}"
