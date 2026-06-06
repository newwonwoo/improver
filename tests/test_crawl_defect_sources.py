"""S1 결함소스 수집기 — 정규화/적재 동작(라이브 fetch는 제외)."""
import json
from scripts.crawl_defect_sources import _norm_article, parse_ccourt, ingest_local


def test_norm_article():
    assert _norm_article("제12조제4항제2호") == "제12조"
    assert _norm_article("130조") == "제130조"
    assert _norm_article("제34조의2제1항") == "제34조의2"


def test_adapter_normalizes():
    rec = parse_ccourt({"law": "산업안전보건법", "article": "제161조제1항",
                        "case_no": "2024헌가1", "text": "..."}).normalized()
    assert rec["source"] == "ccourt"
    assert rec["article"] == "제161조"
    assert rec["defect_type"] == "위헌결정"


def test_ingest_local(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(
        {"law": "주택법", "article": "제15조", "doc_id": "BAI-1", "text": "지적"}),
        encoding="utf-8")
    recs = ingest_local("bai", tmp_path)
    assert len(recs) == 1 and recs[0]["law"] == "주택법" and recs[0]["source"] == "bai"
