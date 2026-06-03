#!/usr/bin/env python3
"""NaverSearch 결과를 룰 마이닝 sources/crawled/naver/ 로 저장.

검색 결과 JSON 입력 → 카테고리별 markdown + index.json 저장.
"""
from __future__ import annotations
import json, sys, re
from pathlib import Path
from datetime import datetime

ROOT = Path("/home/user/improver/outputs/rule_mining/sources/crawled/naver")


def clean_html(s: str) -> str:
    """HTML 태그 제거 + 엔티티 디코드."""
    s = re.sub(r"<[^>]+>", "", s or "")
    s = s.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return s.strip()


def save_category(category: str, items: list[dict], query: str) -> int:
    """카테고리별 폴더에 검색 결과 누적 저장."""
    cat_dir = ROOT / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    index_path = cat_dir / "_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"queries": [], "items": []}

    new_count = 0
    seen_urls = {it["url"] for it in index["items"]}
    for it in items:
        url = it.get("originallink") or it.get("link") or ""
        if url in seen_urls or not url:
            continue
        entry = {
            "title": clean_html(it.get("title", "")),
            "desc": clean_html(it.get("description", "")),
            "url": url,
            "naver_link": it.get("link", ""),
            "pubDate": it.get("pubDate", ""),
            "query": query,
            "crawled_at": datetime.now().isoformat(timespec="seconds"),
        }
        index["items"].append(entry)
        seen_urls.add(url)
        new_count += 1

    if query not in index["queries"]:
        index["queries"].append(query)

    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_count


def export_markdown(category: str) -> Path:
    """누적된 index.json → 사람 읽기 좋은 markdown."""
    cat_dir = ROOT / category
    index_path = cat_dir / "_index.json"
    if not index_path.exists():
        return None
    index = json.loads(index_path.read_text(encoding="utf-8"))
    items = sorted(index["items"], key=lambda x: x.get("pubDate", ""), reverse=True)

    cat_name = {
        "bai": "감사원", "ftc": "공정거래위원회", "fss": "금융감독원",
        "moleg": "법제처", "acrc": "국민권익위원회", "court": "대법원",
    }.get(category, category)

    lines = [
        f"# {cat_name} 사례 — NaverSearch 수집",
        f"",
        f"- 검색어: {len(index['queries'])}개 | 누적 사례: {len(items)}건",
        f"- 검색어 목록: {', '.join(index['queries'])}",
        f"",
        f"---",
        f"",
    ]
    for i, it in enumerate(items, 1):
        lines.append(f"## {i}. {it['title']}")
        lines.append(f"")
        lines.append(f"- **출처**: {it['url']}")
        lines.append(f"- **발행일**: {it.get('pubDate', 'n/a')}")
        lines.append(f"- **검색어**: {it.get('query', 'n/a')}")
        lines.append(f"")
        lines.append(f"{it['desc']}")
        lines.append(f"")
    md_path = cat_dir / f"{category}_사례모음.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: save_naver_results.py <category> <query> <stdin_json>")
        sys.exit(1)
    category = sys.argv[1]
    query = sys.argv[2]
    data = json.load(sys.stdin)
    items = data.get("items", [])
    n = save_category(category, items, query)
    print(f"  {category}: +{n} 신규 (총 {len(json.loads((ROOT/category/'_index.json').read_text(encoding='utf-8'))['items'])}건)")
