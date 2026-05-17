#!/usr/bin/env python3
"""legalize-kr 같은 평문 법령 파일 트리에서 law_index.json 빌드.

사용법:
    python scripts/build_index.py <법령_텍스트_디렉토리> --output data/indexes/law_index.json

기대 입력 디렉토리 구조:
    <root>/
      ├─ <법령명1>.txt    또는
      └─ <법령명1>/
          ├─ 본문.txt
          └─ 시행령.txt   (선택)

각 파일에서 "제N조" 패턴을 추출 → article_numbers 배열 생성.
"법령" + "시행령" 짝은 has_enforcement_decree=True로 연결.
약칭 자동 검출은 향후 short_names.json과의 cross-join.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ART_RE = re.compile(r"제(\d+)조(의\d+)?")


def _extract_articles(text: str) -> list[str]:
    seen: list[str] = []
    visited: set[str] = set()
    for m in _ART_RE.finditer(text):
        num = m.group(1) + (m.group(2) or "").replace("의", "의")
        if num in visited:
            continue
        visited.add(num)
        seen.append(num)
    return seen


def _law_files(root: Path) -> list[tuple[str, Path]]:
    """디렉토리 트리에서 (법령명, 파일경로) 쌍을 수집."""
    out: list[tuple[str, Path]] = []
    for p in sorted(root.rglob("*.txt")):
        name = p.stem
        if name.startswith("synthetic_"):
            continue
        out.append((name, p))
    return out


def _short_names(short_names_path: Path | None, law_name: str) -> list[str]:
    if short_names_path is None or not short_names_path.exists():
        return []
    text = short_names_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return data.get(law_name, [])


def build_index(root: Path, *, short_names_path: Path | None = None) -> dict:
    laws: list[dict] = []
    name_to_entry: dict[str, dict] = {}
    for name, path in _law_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        articles = _extract_articles(text)
        entry = {
            "name": name,
            "short_names": _short_names(short_names_path, name),
            "article_count": len(articles),
            "article_numbers": articles,
            "has_enforcement_decree": False,
        }
        laws.append(entry)
        name_to_entry[name] = entry

    # 시행령/시행규칙 짝 연결
    for entry in laws:
        decree_name = entry["name"] + " 시행령"
        if decree_name in name_to_entry:
            entry["has_enforcement_decree"] = True
            entry["enforcement_decree_name"] = decree_name
    return {"laws": laws}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="법령 인덱스 빌더")
    parser.add_argument("root", help="법령 텍스트 파일 디렉토리")
    parser.add_argument(
        "--output", default="data/indexes/law_index.json", help="출력 JSON 경로"
    )
    parser.add_argument(
        "--short-names", default="config/short_names.json",
        help="약칭 사전 JSON (선택)"
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"입력 디렉토리 없음: {root}", file=sys.stderr)
        return 1
    short_names = Path(args.short_names) if Path(args.short_names).exists() else None
    index = build_index(root, short_names_path=short_names)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} — {len(index['laws'])} laws", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
