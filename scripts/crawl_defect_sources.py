#!/usr/bin/env python3
"""S1 — 결함지향(TP 후보) 소스 수집기.

목적: moleg 해석례(해석성, TP 0)와 달리 '법령 결함'을 직접 지적하는 소스를 수집해
      신경망 학습용 TP 라벨 후보를 확보.
대상 소스: 감사원 감사결과(bai) · 헌재 위헌결정(ccourt) · 법제처 법령정비 권고(moleg_revise).

구조:
  - 표준 레코드 스키마(normalize) — 즉시 동작(테스트됨).
  - 소스별 어댑터(parse) — 원본 레코드 → 표준 스키마.
  - live fetch() — 정부 사이트. 현 실행환경은 egress allowlist로 차단되어 미동작(NotImplemented),
    데이터가 로컬에 있으면 ingest_local 로 정규화만 수행.

사용:
    python scripts/crawl_defect_sources.py ingest <source> <raw_dir>
"""
from __future__ import annotations
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "outputs/rule_mining/sources/crawled"

# 표준 결함 레코드 — verdict 후보 export 가 먹는 최소 필드
FIELDS = ("source", "law", "article", "defect_type", "source_ref", "raw_text")


@dataclass
class DefectRecord:
    source: str         # bai | ccourt | moleg_revise
    law: str            # 법령명(코퍼스 폴더명과 매칭 목표)
    article: str        # 정규화 조문(예: 제12조)
    defect_type: str    # 위헌 | 감사지적 | 정비권고 등
    source_ref: str     # 사건번호/문서ID/URL
    raw_text: str       # 원문 발췌

    def normalized(self) -> dict:
        d = asdict(self)
        d["article"] = _norm_article(d["article"])
        return d


def _norm_article(s: str) -> str:
    """'제12조제4항' / '12조' / '제 12 조' → '제12조' 로 정규화(조 단위)."""
    import re
    m = re.search(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?", s or "")
    if not m:
        return (s or "").strip()
    base = f"제{m.group(1)}조"
    return base + (f"의{m.group(2)}" if m.group(2) else "")


# ─── 소스별 어댑터: 원본 레코드(dict) → DefectRecord ───
def parse_bai(raw: dict) -> DefectRecord:
    return DefectRecord("bai", raw.get("law", ""), raw.get("article", ""),
                        "감사지적", raw.get("doc_id", ""), raw.get("text", ""))


def parse_ccourt(raw: dict) -> DefectRecord:
    return DefectRecord("ccourt", raw.get("law", ""), raw.get("article", ""),
                        "위헌결정", raw.get("case_no", ""), raw.get("text", ""))


def parse_moleg_revise(raw: dict) -> DefectRecord:
    return DefectRecord("moleg_revise", raw.get("law", ""), raw.get("article", ""),
                        "정비권고", raw.get("doc_id", ""), raw.get("text", ""))


ADAPTERS = {"bai": parse_bai, "ccourt": parse_ccourt, "moleg_revise": parse_moleg_revise}


def ingest_local(source: str, raw_dir: Path) -> list[dict]:
    """로컬에 받아둔 원본 json들 → 표준 레코드 jsonl."""
    if source not in ADAPTERS:
        raise SystemExit(f"알 수 없는 source: {source} (가능: {list(ADAPTERS)})")
    parse = ADAPTERS[source]
    records = []
    for fp in sorted(Path(raw_dir).glob("*.json")):
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in (raw if isinstance(raw, list) else [raw]):
            records.append(parse(item).normalized())
    out = OUT_DIR / source / "normalized.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return records


def fetch(source: str):  # pragma: no cover - 환경 egress 차단
    raise NotImplementedError(
        f"{source} 라이브 수집은 정부 사이트 접근 필요 — 현 실행환경 egress allowlist 차단. "
        f"원본을 로컬에 받아 `ingest {source} <dir>` 사용.")


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) >= 4 and sys.argv[1] == "ingest":
        recs = ingest_local(sys.argv[2], Path(sys.argv[3]))
        print(f"{len(recs)}건 정규화 → outputs/rule_mining/sources/crawled/{sys.argv[2]}/normalized.jsonl")
    else:
        print(__doc__)
