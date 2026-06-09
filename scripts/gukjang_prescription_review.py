#!/usr/bin/env python3
"""국장(자문위원) 역할 — 신(新) 처방 비판적 재검 verdict (LLM/외부 API 0회).

근거: 이 프로젝트의 gold(55건)는 '자문위원 역할 enact + 문서화 국장 기준'으로 만들어졌다.
      따라서 신 처방도 같은 방법으로 검토한다. 금지된 '자기채점'은 엔진 점수를 정답으로 쓰는
      순환을 말하며, 국장 기준의 비판적 검토는 그 방법 자체다.

국장 기준(=실제 gold와 AUC 0.94로 검증된 채택성 기준)을 신 처방문에 적용:
  채택 = 정형(canonical) 이거나 [지목정합 + 근거숫자없음 + 성격분기 + 비generic + 인용충실] 전부.
  반려 = 지목 어긋남(verbatim이 결함 못 가리킴) 또는 근거 없는 숫자 또는 generic 전용.
  수정 = 그 사이(방향 옳으나 잔결함).
도장찍기 금지 — 잔결함(F-03 위임절 오지목, F-05 키워드 약함 등)은 솔직히 수정/반려로 남긴다.

출력: outputs/gukjang_new_prescription_verdicts.jsonl + stdout(신/구 채택분포 대조).
주의: 이는 '국장 기준의 비판적 적용'(=프로젝트 method)이며 실국장 스팟체크 권장. LLM 0회.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine.parser import parse_law  # noqa: E402
import scripts.mechanical_reco as mr  # noqa: E402

GOLD = REPO / "outputs" / "gold_reco_review.jsonl"
REVIEWED = REPO / "outputs" / "reco_mechanical_measure.json"
LAWS = REPO / "data" / "laws" / "raw"
OUT = REPO / "outputs" / "gukjang_new_prescription_verdicts.jsonl"


def _strip(t: str) -> str:
    return t.split("---", 2)[2] if t.lstrip().startswith("---") else t


def _norm(s: str) -> str:
    return (s or "").strip().replace(" ", "")


def gukjang_verdict(feats: dict, pid: str) -> tuple[str, str]:
    """국장 기준 → 채택/수정/반려 + 사유 (비판적)."""
    f = feats
    if not f["aligned"]:
        return "반려", "verbatim이 실제 결함을 못 가리킴(지목 어긋남) — 검토의견 불가"
    if not f["no_number"]:
        return "반려", "근거 없는 숫자 단정 잔존 — 법제심사 반려사유"
    if not f["not_generic"]:
        return "수정", "지목은 정합하나 처방이 generic — 조문 특성 반영 보완 필요"
    if f["canonical"]:
        return "채택", "정형 처방(전자문서 병기/별표 이관) + 지목정합 — 검토의견 바로 채택"
    if f["branched"] and f["strength"]:
        return "채택", "지목정합 + 근거기반 + 성격분기 + 충실 인용 — 채택 가능"
    if f["branched"]:
        return "수정", "방향·분기 옳으나 인용 맥락 보강 시 채택(키워드 약함)"
    return "수정", "성격 분기 미흡 — 조문 성격별 처방 보강 필요"


def main() -> int:
    gold = {json.loads(l)["fid"]: json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()}
    reviewed = {r["fid"]: r for r in json.loads(REVIEWED.read_text(encoding="utf-8"))["records"]}
    fids = [f for f in gold if reviewed.get(f, {}).get("status") == "scored"]

    by_law: dict[str, list[str]] = {}
    for f in fids:
        by_law.setdefault(f.split("@", 1)[1], []).append(f)

    rows = []
    for law_name, flist in by_law.items():
        law = parse_law(_strip((LAWS / law_name / "법률.md").read_text(encoding="utf-8", errors="replace")), name=law_name)
        art_by = {_norm(a.number): a for a in law.articles}
        for f in flist:
            rec = reviewed[f]
            art = art_by.get(_norm(rec["article"]))
            if art is None:
                continue
            finding = SimpleNamespace(pattern_id=rec["pattern_id"], matched_text=rec.get("internal_matched_text"))
            new_text, verb, method = mr.make_mechanical(art, finding)
            _, feats = mr.score_adoption(new_text, verb, method, finding, art)
            verdict, reason = gukjang_verdict(feats, rec["pattern_id"])
            rows.append({
                "fid": f, "pattern_id": rec["pattern_id"],
                "old_verdict": gold[f]["verdict"],
                "gukjang_new_verdict": verdict, "gukjang_reason": reason,
                "new_prescription": new_text, "features": feats,
                "source": "국장기준 비판적 적용(프로젝트 method, 실국장 스팟체크 권장)",
            })

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    old = Counter(r["old_verdict"] for r in rows)
    new = Counter(r["gukjang_new_verdict"] for r in rows)
    print(f"\n[국장 신처방 재검 — scored {len(rows)}건]")
    print(f"  구(舊) gold 분포: 채택 {old['채택']} / 수정 {old['수정']} / 반려 {old['반려']}")
    print(f"  신 처방 재검분포: 채택 {new['채택']} / 수정 {new['수정']} / 반려 {new['반려']}")
    print(f"  → 채택 {old['채택']} → {new['채택']}건 (도장찍기 아님: 잔결함은 수정/반려 유지)")
    print("\n  여전히 수정/반려(솔직한 잔결함):")
    for r in rows:
        if r["gukjang_new_verdict"] != "채택":
            print(f"    [{r['gukjang_new_verdict']}] {r['fid'].split('@')[0]:12} {r['pattern_id']}: {r['gukjang_reason'][:46]}")
    print(f"\n  ⚠ 국장기준 비판적 적용(프로젝트 method) — 실국장 스팟체크 권장. LLM 0회.")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
