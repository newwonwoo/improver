"""일괄 분석 CLI 동작 확인."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_batch_cli_produces_summary(tmp_path):
    laws = tmp_path / "laws"
    laws.mkdir()
    (laws / "테스트법1.txt").write_text(
        "제1조(목적) 본문.\n제10조(재량) 장관은 필요하다고 인정하면 처분할 수 있다.\n",
        encoding="utf-8",
    )
    (laws / "테스트법2.txt").write_text(
        "제1조(목적) 본문.\n제5조(면책) 일체의 책임을 지지 아니한다.\n",
        encoding="utf-8",
    )
    out = tmp_path / "results"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "analyze_batch.py"),
         str(laws), "--output-dir", str(out), "--workers", "2"],
        check=True, capture_output=True, text=True,
    )
    summary = json.loads((out / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["total_laws"] == 2
    names = {s["name"] for s in summary["all"]}
    assert names == {"테스트법1", "테스트법2"}
    # 개별 결과 파일도 존재해야
    assert (out / "테스트법1.json").exists()
    assert (out / "테스트법2.json").exists()
