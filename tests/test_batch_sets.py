"""법령 세트 일괄 분석 + judgment_md(시행령 부록) 통합 테스트."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _write_law_set(root: Path, name: str, body: str, decree: str | None = None,
                    rule: str | None = None):
    d = root / name
    d.mkdir(parents=True)
    (d / "법률.md").write_text(body, encoding="utf-8")
    if decree:
        (d / "시행령.md").write_text(decree, encoding="utf-8")
    if rule:
        (d / "시행규칙.md").write_text(rule, encoding="utf-8")


LAW_BODY = """\
---
제목: 테스트법
법령구분: 법률
시행일자: 2026-01-01
공포일자: 2025-12-01
---

# 테스트법

##### 제1조 (목적)

이 법은 테스트를 위한 법이다.

##### 제22조 (업무지침)

수탁기관은 업무지침을 정하여야 한다.

##### 제12조 (감독)

장관은 기금을 감독한다.
"""

DECREE_BODY = """\
---
제목: 테스트법 시행령
법령구분: 대통령령
---

# 테스트법 시행령

##### 제22조 (업무지침 세부)

업무지침은 다음 각 호의 사항을 포함한다.

##### 제12조 (감독 절차)

감독은 매년 1회 실시한다.
"""


def test_batch_sets_generates_judgment_with_decree_appendix(tmp_path):
    raw = tmp_path / "raw"
    _write_law_set(raw, "테스트법", LAW_BODY, decree=DECREE_BODY)
    out = tmp_path / "out"

    subprocess.run([
        sys.executable, str(REPO / "scripts" / "analyze_batch_sets.py"),
        str(raw), "--output-dir", str(out), "--workers", "1",
    ], check=True, capture_output=True, text=True)

    summary = json.loads((out / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["ok"] == 1
    assert summary["all"][0]["has_decree"] is True
    md = (out / "judgments" / "테스트법.md").read_text(encoding="utf-8")
    # 시행령 부록 포함되어야
    assert "부록 A — 시행령 전문" in md
    assert "테스트법 시행령" in md
    # 법률 조문 + 시행령 매핑 인라인
    assert "🔗 위임" in md or "[시행령]" in md
    # 시행령 본문 자체도 부록에 있어야
    assert "감독 절차" in md


def test_batch_sets_marks_missing_decree(tmp_path):
    raw = tmp_path / "raw"
    _write_law_set(raw, "단독법", LAW_BODY)  # 시행령 없음
    out = tmp_path / "out"
    subprocess.run([
        sys.executable, str(REPO / "scripts" / "analyze_batch_sets.py"),
        str(raw), "--output-dir", str(out), "--workers", "1",
    ], check=True, capture_output=True)
    md = (out / "judgments" / "단독법.md").read_text(encoding="utf-8")
    assert "시행령 없음" in md
    assert "부록 A" not in md


def test_batch_sets_skips_empty_law(tmp_path):
    raw = tmp_path / "raw"
    _write_law_set(raw, "폐지법", """---
제목: 폐지법
---
# 폐지법
폐지한다.
""")
    out = tmp_path / "out"
    subprocess.run([
        sys.executable, str(REPO / "scripts" / "analyze_batch_sets.py"),
        str(raw), "--output-dir", str(out), "--workers", "1",
    ], check=True, capture_output=True)
    summary = json.loads((out / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary["skipped"] == 1
    assert "조문 0개" in summary["skipped_list"][0]["reason"]
