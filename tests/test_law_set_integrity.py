"""법률·시행령·시행규칙 세트 정합성 검증.

배치 분석으로 만들어진 judgment MD와 raw 디렉토리·인덱스가 서로 모순되지
않는지 확인한다. 큰 회귀가 생겼을 때 빠르게 잡기 위한 산출물 단위 테스트.

raw 디렉토리나 인덱스가 없으면 자동 skip — 개발 환경 차이를 허용.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "laws" / "raw"
INDEX = REPO / "data" / "indexes" / "law_index.json"
JUDGMENTS = REPO / "outputs" / "judgments"
SUMMARY = REPO / "outputs" / "batch_summary.json"


def _have_full_dataset() -> bool:
    return RAW.exists() and INDEX.exists()


@pytest.mark.skipif(not _have_full_dataset(), reason="full raw dataset 미존재")
def test_directory_law_count_matches_index():
    """디렉토리의 법률.md 개수 = 인덱스의 법률(시행령·시행규칙 제외) 개수."""
    dir_count = sum(1 for d in RAW.iterdir() if d.is_dir() and (d / "법률.md").exists())
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    idx_count = sum(
        1 for l in idx["laws"]
        if not l["name"].endswith(("시행령", "시행규칙"))
    )
    assert dir_count == idx_count, (
        f"디렉토리 법률 {dir_count}건 vs 인덱스 법률 {idx_count}건 — 빌드 후 인덱스 갱신 필요"
    )


@pytest.mark.skipif(not _have_full_dataset(), reason="full raw dataset 미존재")
def test_directory_decree_count_matches_index_has_decree():
    """디렉토리의 시행령.md 개수 = 인덱스 has_enforcement_decree=True 개수."""
    dir_count = sum(
        1 for d in RAW.iterdir() if d.is_dir() and (d / "시행령.md").exists()
    )
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    laws_only = [l for l in idx["laws"]
                 if not l["name"].endswith(("시행령", "시행규칙"))]
    idx_has_decree = sum(1 for l in laws_only if l.get("has_enforcement_decree"))
    assert dir_count == idx_has_decree


@pytest.mark.skipif(not _have_full_dataset(), reason="full raw dataset 미존재")
def test_no_orphan_decree_in_directory():
    """디렉토리에 시행령.md 있는 법령은 인덱스 'has_enforcement_decree=True'여야."""
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    laws_only = {l["name"]: l for l in idx["laws"]
                 if not l["name"].endswith(("시행령", "시행규칙"))}
    orphans: list[str] = []
    for d in RAW.iterdir():
        if not d.is_dir() or not (d / "시행령.md").exists():
            continue
        entry = laws_only.get(d.name)
        if entry is None:
            continue
        if not entry.get("has_enforcement_decree"):
            orphans.append(d.name)
    assert not orphans, f"인덱스가 누락한 시행령 매핑: {orphans[:5]}"


@pytest.mark.skipif(not JUDGMENTS.exists() or not SUMMARY.exists(),
                    reason="batch judgment 산출물 미존재")
def test_judgment_md_count_matches_summary_ok():
    """판단용 MD 개수 = batch_summary.json의 OK 개수."""
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    md_count = len(list(JUDGMENTS.glob("*.md")))
    assert md_count == s["ok"]


@pytest.mark.skipif(not JUDGMENTS.exists() or not RAW.exists(),
                    reason="batch judgment 산출물 미존재")
def test_judgment_md_includes_decree_when_present():
    """raw에 시행령.md가 있고 MD가 생성된 법령은 부록 A 포함되어야."""
    missing: list[str] = []
    for d in RAW.iterdir():
        if not d.is_dir() or not (d / "시행령.md").exists():
            continue
        md = JUDGMENTS / f"{d.name}.md"
        if not md.exists():
            continue  # skip된 법령
        if "부록 A — 시행령 전문" not in md.read_text(encoding="utf-8"):
            missing.append(d.name)
    assert not missing, (
        f"시행령은 있는데 부록 A가 빠진 MD: {len(missing)}건 "
        f"(샘플: {missing[:3]})"
    )


@pytest.mark.skipif(not JUDGMENTS.exists() or not RAW.exists(),
                    reason="batch judgment 산출물 미존재")
def test_judgment_md_includes_rule_when_present():
    """시행규칙도 동일하게 부록 B 포함되어야."""
    missing: list[str] = []
    for d in RAW.iterdir():
        if not d.is_dir() or not (d / "시행규칙.md").exists():
            continue
        md = JUDGMENTS / f"{d.name}.md"
        if not md.exists():
            continue
        if "부록 B — 시행규칙 전문" not in md.read_text(encoding="utf-8"):
            missing.append(d.name)
    assert not missing, (
        f"시행규칙은 있는데 부록 B가 빠진 MD: {len(missing)}건"
    )


def test_judgment_md_rule_mapping_inline_format():
    """렌더된 MD가 시행규칙 매핑 블록 형식을 정확히 따르는지 (단독 테스트)."""
    from engine import cases, fpc, judgment_md, recommender, scorer
    from engine.adapters import normalize_legalize_md
    from engine.parser import parse_law
    from engine.rules import run_all

    law_md = """---
제목: 테스트법
법령구분: 법률
---
##### 제5조 (위임)
이 법 시행에 필요한 사항은 부령으로 정한다.
"""
    rule_md = """---
제목: 테스트법 시행규칙
---
##### 제5조 (시행규칙 본문)
별지 제1호 서식을 사용한다.
"""
    law_body, _ = normalize_legalize_md(law_md)
    rule_body, _ = normalize_legalize_md(rule_md)
    law = parse_law(law_body, name="테스트법", law_category="일반")
    rule_law = parse_law(rule_body, name="테스트법 시행규칙", law_type="부령")
    findings = fpc.correct(law, run_all(law))
    result = scorer.compute(law, findings)
    result = recommender.apply(result)
    result = cases.attach(result)
    md = judgment_md.render(result, rule=rule_law)
    assert "🔗 위임 → 시행규칙 매핑 후보" in md
    assert "부록 B — 시행규칙 전문" in md
