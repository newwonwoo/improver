#!/usr/bin/env python3
"""
Phase 13 verdict batch 응답 → verification_dataset.jsonl 통합

응답 JSON 형식 (Claude.ai 가 반환):
{
  "verdicts": [
    {"id": 1, "verdict": "TP|FP|BORDER", "rule_id": "R-...", "reason": "..."},
    ...
  ]
}

batch_NN.md 의 #N 번호 ↔ 응답 verdict.id 매칭
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
RESP_DIR = ROOT / "outputs/phase13_verdict_responses"
DATASET = ROOT / "outputs/verification_dataset.jsonl"

def main():
    if not RESP_DIR.exists():
        print(f"응답 폴더 없음: {RESP_DIR}")
        print("Claude.ai 응답을 batch_01.json, batch_02.json ... 형태로 저장 후 재실행")
        return
    response_files = sorted(RESP_DIR.glob("batch_*.json"))
    if not response_files:
        print(f"응답 파일 없음. {RESP_DIR}/batch_NN.json 형태로 저장 필요")
        return

    new_records = []
    for fp in response_files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  {fp.name} 파싱 실패: {e}")
            continue
        verdicts = data.get("verdicts", [])
        for v in verdicts:
            verdict = v.get("verdict", "").upper()
            if verdict not in ("TP", "FP", "BORDER"):
                continue
            rule_id = v.get("rule_id", "")
            if not rule_id:
                continue
            # fid 생성 — moleg 기반이므로 batch_id + idx 로 unique 키
            batch_id = fp.stem
            item_id = v.get("id", 0)
            record = {
                "bundle_id": f"phase13_{batch_id}",
                "rule_id": rule_id,
                "fid": f"{rule_id}-{batch_id}-{item_id}",
                "verdict": verdict,
                "evidence": v.get("reason", "")[:300],
            }
            new_records.append(record)
        print(f"  {fp.name}: {len(verdicts)} verdicts")

    if not new_records:
        print("적재할 verdict 없음")
        return

    # Append to verification_dataset.jsonl
    with open(DATASET, "a", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n{len(new_records)}건 추가 → {DATASET}")
    print(f"다음: torch 재학습 → python -c \"from engine.slm.torch_brain import train_torch; train_torch()\"")


if __name__ == "__main__":
    main()
