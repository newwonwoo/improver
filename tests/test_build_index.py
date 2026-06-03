"""법령 인덱스 빌더 단위 테스트."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_build_index_extracts_articles(tmp_path):
    root = tmp_path / "laws"
    root.mkdir()
    (root / "테스트법.txt").write_text(
        "제1조(목적) 본문.\n제2조(정의) 본문.\n제10조(요건) 본문.\n",
        encoding="utf-8",
    )
    out = tmp_path / "law_index.json"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_index.py"),
         str(root), "--output", str(out),
         "--short-names", "/dev/null"],
        check=True, capture_output=True, text=True,
    )
    index = json.loads(out.read_text(encoding="utf-8"))
    laws = {l["name"]: l for l in index["laws"]}
    assert "테스트법" in laws
    assert laws["테스트법"]["article_numbers"] == ["1", "2", "10"]


def test_build_index_links_decree(tmp_path):
    root = tmp_path / "laws"
    root.mkdir()
    (root / "테스트법.txt").write_text("제1조(목적) 본문.\n", encoding="utf-8")
    (root / "테스트법 시행령.txt").write_text("제1조(시행) 본문.\n", encoding="utf-8")
    out = tmp_path / "law_index.json"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_index.py"),
         str(root), "--output", str(out),
         "--short-names", "/dev/null"],
        check=True,
    )
    index = json.loads(out.read_text(encoding="utf-8"))
    parent = next(l for l in index["laws"] if l["name"] == "테스트법")
    assert parent["has_enforcement_decree"] is True
    assert parent["enforcement_decree_name"] == "테스트법 시행령"


def test_build_index_applies_short_names(tmp_path):
    root = tmp_path / "laws"
    root.mkdir()
    (root / "테스트법.txt").write_text("제1조 본문.\n", encoding="utf-8")
    short = tmp_path / "short.json"
    short.write_text(json.dumps({"테스트법": ["테법", "tlaw"]}), encoding="utf-8")
    out = tmp_path / "law_index.json"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_index.py"),
         str(root), "--output", str(out), "--short-names", str(short)],
        check=True,
    )
    index = json.loads(out.read_text(encoding="utf-8"))
    parent = next(l for l in index["laws"] if l["name"] == "테스트법")
    assert "테법" in parent["short_names"]
