#!/usr/bin/env python3
"""
Phase 13 verdict batch 응답 → verification_dataset.jsonl 통합 (트레이너 호환)

응답 JSON 형식:
{
  "verdicts": [
    {"id": 1, "verdict": "TP|FP|BORDER", "rule_id": "R-...", "reason": "..."},
    ...
  ]
}

batch_v2_NN.json 의 within-batch id ↔ phase13_verdict_candidates_v2.jsonl 전역 후보 매핑.
fid 는 트레이너(collect_torch_data)가 파싱하는 형식 `{rule_id}@{법령명}` 으로 생성하고,
fid_article_map[fid] = primary_article_norm 을 자동 등록한다.
(과거 `{rule}-{batch}-{id}` 형식은 트레이너가 전부 스킵 → 학습 0행 버그였음)
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
RESP_DIR = ROOT / "outputs/phase13_verdict_responses"
DATASET = ROOT / "outputs/verification_dataset.jsonl"
CAND_FILE = ROOT / "outputs/phase13_verdict_candidates_v2.jsonl"
FID_MAP = ROOT / "outputs/fid_article_map.json"
BATCH_SIZE = 8  # batch_v2_NN.md 당 후보 수 (export 스크립트와 일치)


def _load_candidates() -> list[dict]:
    if not CAND_FILE.exists():
        return []
    return [json.loads(l) for l in CAND_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]


def _batch_num(stem: str) -> int | None:
    m = re.search(r"(\d+)\s*$", stem)
    return int(m.group(1)) if m else None


def main():
    if not RESP_DIR.exists():
        print(f"응답 폴더 없음: {RESP_DIR}")
        return
    response_files = sorted(RESP_DIR.glob("batch_*.json"))
    if not response_files:
        print(f"응답 파일 없음. {RESP_DIR}/batch_NN.json 형태로 저장 필요")
        return

    candidates = _load_candidates()
    try:
        from engine.slm.learn import RULE_CAT, REASONING_RULE_CAT
        _known = set(RULE_CAT) | set(REASONING_RULE_CAT)
    except Exception:
        _known = set()

    fid_map: dict[str, str] = {}
    if FID_MAP.exists():
        fid_map = json.loads(FID_MAP.read_text(encoding="utf-8"))

    new_records = []
    skipped_no_cat = 0
    for fp in response_files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  {fp.name} 파싱 실패: {e}")
            continue
        bnum = _batch_num(fp.stem)
        verdicts = data.get("verdicts", [])
        used = 0
        for v in verdicts:
            verdict = v.get("verdict", "").upper()
            if verdict not in ("TP", "FP", "BORDER"):
                continue
            rule_id = v.get("rule_id", "")
            if not rule_id:
                continue
            if _known and rule_id not in _known:
                skipped_no_cat += 1
                print(f"    ⚠️ {fp.name}#{v.get('id')}: rule_id '{rule_id}' 카테고리 미매핑 → 학습 제외")
                continue
            # within-batch id → 전역 후보 매핑
            item_id = int(v.get("id", 0))
            cand = None
            if bnum is not None and candidates:
                gidx = (bnum - 1) * BATCH_SIZE + item_id - 1
                if 0 <= gidx < len(candidates):
                    cand = candidates[gidx]
            if not cand:
                print(f"    ⚠️ {fp.name}#{item_id}: 후보 매핑 실패 → 스킵")
                continue
            law = cand.get("primary_law", "")
            an = cand.get("primary_article_norm", "")
            if not law or not an:
                print(f"    ⚠️ {fp.name}#{item_id}: 후보에 법령/조문 없음 → 스킵")
                continue
            fid = f"{rule_id}@{law}"          # 트레이너 파싱 형식
            fid_map[fid] = an                 # 조문 매핑 등록
            new_records.append({
                "bundle_id": f"phase13_{fp.stem}",
                "rule_id": rule_id,
                "fid": fid,
                "verdict": verdict,
                "evidence": v.get("reason", "")[:300],
            })
            used += 1
        print(f"  {fp.name}: {used}/{len(verdicts)} 적재")

    if not new_records:
        print("적재할 verdict 없음")
        return

    with open(DATASET, "a", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    FID_MAP.write_text(json.dumps(fid_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(new_records)}건 추가 → {DATASET.name}")
    print(f"fid_article_map 갱신 → {FID_MAP.name} (+{len(new_records)} fid)")
    if skipped_no_cat:
        print(f"⚠️ 카테고리 미매핑 {skipped_no_cat}건 제외 (RULE_CAT/REASONING_RULE_CAT 확인)")
    print('다음: python -c "from engine.slm.torch_brain import train_torch; train_torch()"')


if __name__ == "__main__":
    main()
