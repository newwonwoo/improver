"""검토된 후보 → config 병합 테스트."""
import json
from pathlib import Path

from engine.proposal_applier import (
    apply_case_candidates,
    apply_template_candidates,
)


def _write(p: Path, payload):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_only_approved_cases_merged(tmp_path):
    cand = tmp_path / "case_candidates.json"
    tgt = tmp_path / "disciplinary_cases.json"
    _write(cand, {"candidates": [
        {"case_id": "LLM-aaa", "agency": "감사원", "summary": "x",
         "approved": True, "source_law": "법령A"},
        {"case_id": "LLM-bbb", "agency": "공정위", "summary": "y",
         "source_law": "법령B"},  # approved 없음
    ]})
    _write(tgt, {"cases": []})

    r = apply_case_candidates(candidates_path=cand, target_path=tgt)
    assert r.cases_added == ["LLM-aaa"]
    target = json.loads(tgt.read_text(encoding="utf-8"))
    assert len(target["cases"]) == 1
    assert target["cases"][0]["case_id"] == "LLM-aaa"


def test_duplicate_case_id_skipped(tmp_path):
    cand = tmp_path / "case_candidates.json"
    tgt = tmp_path / "disciplinary_cases.json"
    _write(cand, {"candidates": [
        {"case_id": "X-001", "agency": "감사원", "summary": "x", "approved": True,
         "source_law": "법령A"},
    ]})
    _write(tgt, {"cases": [{"case_id": "X-001", "agency": "감사원", "summary": "old"}]})

    r = apply_case_candidates(candidates_path=cand, target_path=tgt)
    assert "X-001" in r.cases_skipped
    assert "X-001" not in r.cases_added


def test_dry_run_does_not_modify_target(tmp_path):
    cand = tmp_path / "case_candidates.json"
    tgt = tmp_path / "disciplinary_cases.json"
    _write(cand, {"candidates": [
        {"case_id": "X-002", "agency": "감사원", "summary": "x", "approved": True,
         "source_law": "법령A"},
    ]})
    _write(tgt, {"cases": []})
    before = tgt.read_text(encoding="utf-8")
    r = apply_case_candidates(candidates_path=cand, target_path=tgt, dry_run=True)
    assert r.cases_added == ["X-002"]
    assert tgt.read_text(encoding="utf-8") == before  # 파일 그대로


def test_backup_created_on_apply(tmp_path):
    cand = tmp_path / "case_candidates.json"
    tgt = tmp_path / "disciplinary_cases.json"
    _write(cand, {"candidates": [
        {"case_id": "X-003", "agency": "감사원", "summary": "x", "approved": True,
         "source_law": "법령A"},
    ]})
    _write(tgt, {"cases": [{"case_id": "EXISTING", "agency": "감사원", "summary": "x"}]})
    r = apply_case_candidates(candidates_path=cand, target_path=tgt)
    assert r.backups_created
    bak = Path(r.backups_created[0])
    assert bak.exists()
    # 백업은 원본 그대로
    assert "EXISTING" in bak.read_text(encoding="utf-8")


def test_template_added_when_no_existing(tmp_path):
    cand = tmp_path / "template_candidates.json"
    tgt = tmp_path / "recommendations.json"
    _write(cand, {"candidates": [
        {"pattern_id": "X-NEW1", "severity": "심각",
         "suggested_template": "새 권고", "approved": True},
    ]})
    _write(tgt, {})
    r = apply_template_candidates(candidates_path=cand, target_path=tgt)
    assert "X-NEW1/심각" in r.templates_added
    target = json.loads(tgt.read_text(encoding="utf-8"))
    assert target["X-NEW1"]["심각"] == "새 권고"


def test_template_skipped_when_existing_without_overwrite(tmp_path):
    cand = tmp_path / "template_candidates.json"
    tgt = tmp_path / "recommendations.json"
    _write(cand, {"candidates": [
        {"pattern_id": "G-04", "severity": "심각",
         "suggested_template": "LLM 제안", "approved": True},
    ]})
    _write(tgt, {"G-04": {"심각": "기존 표준 권고"}})
    r = apply_template_candidates(candidates_path=cand, target_path=tgt,
                                   overwrite=False)
    assert any("G-04/심각" in s for s in r.templates_skipped)
    target = json.loads(tgt.read_text(encoding="utf-8"))
    assert target["G-04"]["심각"] == "기존 표준 권고"  # 변경 안 됨


def test_template_overwritten_with_flag(tmp_path):
    cand = tmp_path / "template_candidates.json"
    tgt = tmp_path / "recommendations.json"
    _write(cand, {"candidates": [
        {"pattern_id": "G-04", "severity": "심각",
         "suggested_template": "LLM 제안", "approved": True},
    ]})
    _write(tgt, {"G-04": {"심각": "기존 표준"}})
    r = apply_template_candidates(candidates_path=cand, target_path=tgt,
                                   overwrite=True)
    assert "G-04/심각" in r.templates_replaced
    target = json.loads(tgt.read_text(encoding="utf-8"))
    assert target["G-04"]["심각"] == "LLM 제안"
