#!/usr/bin/env python3
"""정부 사이트 자료 크롤러 — 룰 마이닝용 원자료 수집.

대상:
  1. 공정위 의결서 (case.ftc.go.kr) — 약관 시정명령
  2. 공정위 보도자료 (ftc.go.kr) — 약관 심사 결과
  3. 감사원 감사결과 (bai.go.kr) — 처분요구·개선통보
  4. 정책브리핑 (korea.kr) — 부처별 시정 보도자료
  5. casenote.kr — 공정위 의결문·대법원 행정판례
  6. 법제처 법령해석 (moleg.go.kr) — 위임 명확성 해석례
  7. 금감원 제재공시 (fss.or.kr) — 검사·제재 결과

샌드박스에서는 정부 사이트가 차단되므로 **로컬 환경에서 실행** 필요.

사용:
  pip install requests beautifulsoup4
  python scripts/crawl_rule_sources.py [--source ftc|bai|acrc|fss|all]
                                       [--max-items 50]
                                       [--out outputs/rule_mining/sources/crawled]

수집 결과:
  outputs/rule_mining/sources/crawled/<source>/<date>_<title>.{md,pdf}
  outputs/rule_mining/sources/crawled/index.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse, parse_qs

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: pip install requests beautifulsoup4", file=sys.stderr)
    sys.exit(1)

# 기본 헤더 — 정상 브라우저 위장
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

SLEEP = 1.0  # 요청 간 대기 (서버 부하 방지)


def _slug(text: str, max_len: int = 50) -> str:
    """파일명용 슬러그 — 한글/숫자/언더스코어만 유지."""
    s = re.sub(r"[^\w가-힣]+", "_", text.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len]


def _hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:8]


def _save(out_dir: Path, name: str, content: str, meta: dict) -> Path:
    """수집한 자료를 md + json 메타데이터로 저장."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{name}.md"
    md_path.write_text(content, encoding="utf-8")
    (out_dir / f"{name}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return md_path


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    # ConnectionReset·5xx·429 에 대한 자동 재시도 (지수 백오프)
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry = Retry(
            total=4, connect=4, read=4, backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    except Exception:
        pass
    return s


# ============ 1. 공정위 보도자료 ============

def crawl_ftc_press(out_root: Path, max_items: int = 50) -> int:
    """공정거래위원회 보도자료 — 약관·시정명령 키워드 필터링."""
    out_dir = out_root / "ftc_press"
    sess = _session()
    base = "https://www.ftc.go.kr"
    list_url = f"{base}/www/ReportUserList.do"  # 구 selectReportList.do 폐기 → 신 엔드포인트

    keywords = ["약관", "시정", "불공정", "표준약관"]
    saved = 0

    consec_fail = 0
    for page in range(1, 21):
        if saved >= max_items or consec_fail >= 3:
            if consec_fail >= 3:
                print(f"  [ftc] 연속 {consec_fail}회 실패 — 중단 (접근 차단 가능성)")
            break
        params = {
            "pageUnit": "10",
            "pageIndex": str(page),
            "key": "164",
            "rpttype": "1",
            "searchCnd": "all",
        }
        try:
            r = sess.get(list_url, params=params, timeout=15)
            r.raise_for_status()
            consec_fail = 0
        except Exception as e:
            consec_fail += 1
            print(f"  [ftc] page {page} 실패: {e}")
            time.sleep(SLEEP)
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table.board_list tbody tr") or soup.select("li.board_li")
        if not rows:
            print(f"  [ftc] page {page} 행 없음 (구조 변경?)")
            break

        for row in rows:
            link = row.find("a")
            if not link:
                continue
            title = link.get_text(strip=True)
            if not any(kw in title for kw in keywords):
                continue

            href = link.get("href", "")
            detail_url = urljoin(base, href) if href.startswith("/") else href
            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception:
                continue

            dsoup = BeautifulSoup(d.text, "html.parser")
            content = dsoup.select_one(".board_view, .view_cont, .cont_view, article")
            text = content.get_text("\n", strip=True) if content else d.text
            date_m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
            date_str = date_m.group(0) if date_m else "unknown"

            name = f"{date_str}_{_slug(title)}_{_hash(detail_url)}"
            meta = {
                "source": "ftc_press",
                "title": title,
                "url": detail_url,
                "crawled_at": datetime.now().isoformat(),
            }
            md_content = f"# {title}\n\n출처: {detail_url}\n수집일: {meta['crawled_at']}\n\n---\n\n{text}"
            _save(out_dir, name, md_content, meta)
            saved += 1
            print(f"  [ftc] saved ({saved}): {title[:60]}")
            time.sleep(SLEEP)
            if saved >= max_items:
                break
        time.sleep(SLEEP)
    return saved


# ============ 2. 공정위 의결서 (case.ftc.go.kr) ============

def crawl_ftc_decisions(out_root: Path, max_items: int = 50) -> int:
    """공정위 의결서 — 약관·불공정거래 의결 자동 수집."""
    out_dir = out_root / "ftc_decisions"
    sess = _session()
    base = "https://case.ftc.go.kr"
    list_url = f"{base}/ocp/co/ltfr.do"
    saved = 0

    for page in range(1, 11):
        if saved >= max_items:
            break
        params = {"pageIndex": str(page), "searchKrwd": "약관"}
        try:
            r = sess.get(list_url, params=params, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(f"  [ftc_dec] page {page} 실패: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table tbody tr")
        for row in rows:
            link = row.find("a")
            if not link:
                continue
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if "javascript:" in href:
                onclick = link.get("onclick", "") or href
                m = re.search(r"['\"]([0-9]+)['\"]", onclick)
                if not m:
                    continue
                detail_url = f"{base}/ocp/co/ltfrViewPopup.do?dispNo={m.group(1)}"
            else:
                detail_url = urljoin(base, href)

            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception:
                continue

            dsoup = BeautifulSoup(d.text, "html.parser")
            text = dsoup.get_text("\n", strip=True)
            name = f"{_slug(title)}_{_hash(detail_url)}"
            md = f"# {title}\n\n출처: {detail_url}\n\n---\n\n{text}"
            _save(out_dir, name, md, {
                "source": "ftc_decisions",
                "title": title,
                "url": detail_url,
                "crawled_at": datetime.now().isoformat(),
            })
            saved += 1
            print(f"  [ftc_dec] saved ({saved}): {title[:60]}")
            time.sleep(SLEEP)
            if saved >= max_items:
                break
        time.sleep(SLEEP)
    return saved


# ============ 3. 감사원 감사결과 ============

def crawl_bai(out_root: Path, max_items: int = 30) -> int:
    """감사원 감사결과 보고서 — 처분요구·개선통보 수집."""
    out_dir = out_root / "bai"
    sess = _session()
    base = "https://www.bai.go.kr"
    list_url = f"{base}/bai/down/publication/decisionAuditList/"  # 처분요구 주요사항 목록 (구 proactive 경로 폐기)
    saved = 0

    for page in range(1, 6):
        if saved >= max_items:
            break
        try:
            r = sess.get(list_url, params={"pageIndex": str(page)}, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(f"  [bai] page {page} 실패: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("li, tr")
        for row in rows:
            link = row.find("a", href=True)
            if not link:
                continue
            title = link.get_text(strip=True)
            if len(title) < 5:
                continue
            href = link.get("href", "")
            detail_url = urljoin(base, href)

            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception:
                continue
            dsoup = BeautifulSoup(d.text, "html.parser")

            # PDF 첨부 다운로드
            pdf_links = [
                urljoin(detail_url, a["href"])
                for a in dsoup.find_all("a", href=True)
                if any(a["href"].lower().endswith(ext) for ext in [".pdf", ".hwp"])
            ]
            for pdf_url in pdf_links:
                try:
                    pdf_r = sess.get(pdf_url, timeout=30)
                    if pdf_r.ok:
                        ext = pdf_url.rsplit(".", 1)[-1]
                        pdf_name = f"{_slug(title)}_{_hash(pdf_url)}.{ext}"
                        (out_dir / pdf_name).parent.mkdir(parents=True, exist_ok=True)
                        (out_dir / pdf_name).write_bytes(pdf_r.content)
                        print(f"  [bai] pdf saved: {pdf_name}")
                except Exception:
                    pass

            text = dsoup.get_text("\n", strip=True)
            name = f"{_slug(title)}_{_hash(detail_url)}"
            md = f"# {title}\n\n출처: {detail_url}\n\n---\n\n{text}"
            _save(out_dir, name, md, {
                "source": "bai",
                "title": title,
                "url": detail_url,
                "pdf_links": pdf_links,
                "crawled_at": datetime.now().isoformat(),
            })
            saved += 1
            print(f"  [bai] saved ({saved}): {title[:60]}")
            time.sleep(SLEEP)
            if saved >= max_items:
                break
    return saved


# ============ 4. 정책브리핑 (korea.kr) — 부처별 보도자료 ============

def crawl_korea_kr(out_root: Path, max_items: int = 50) -> int:
    """정책브리핑 — 공정위·감사원·권익위·금감원 보도자료 통합 수집."""
    out_dir = out_root / "korea_kr"
    sess = _session()
    base = "https://www.korea.kr"
    saved = 0

    keywords = [
        "불공정약관", "약관 시정", "감사 결과", "감사 처분", "감사원",
        "고충민원", "권익위 권고", "부패영향평가",
        "금감원 제재", "금융감독원 검사", "불완전판매",
    ]

    for kw in keywords:
        if saved >= max_items:
            break
        try:
            r = sess.get(
                f"{base}/search/searchResult.do",
                params={"query": kw, "section": "news"},
                timeout=15,
            )
            r.raise_for_status()
        except Exception as e:
            print(f"  [korea] '{kw}' 실패: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.select("a[href*='policyNewsView'], a[href*='policyBriefingView']")[:10]:
            href = link.get("href", "")
            detail_url = urljoin(base, href)
            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception:
                continue
            dsoup = BeautifulSoup(d.text, "html.parser")
            title = (dsoup.title.string if dsoup.title else link.get_text(strip=True)) or "untitled"
            content_el = dsoup.select_one("#news_content, article, .news_body, .article_view")
            text = content_el.get_text("\n", strip=True) if content_el else dsoup.get_text("\n", strip=True)

            name = f"{_slug(title)}_{_hash(detail_url)}"
            md = f"# {title}\n\n출처: {detail_url}\n키워드: {kw}\n\n---\n\n{text}"
            _save(out_dir, name, md, {
                "source": "korea_kr",
                "title": title,
                "keyword": kw,
                "url": detail_url,
                "crawled_at": datetime.now().isoformat(),
            })
            saved += 1
            print(f"  [korea] ({kw}) saved ({saved}): {title[:60]}")
            time.sleep(SLEEP)
            if saved >= max_items:
                break
    return saved


# ============ 5. casenote.kr — 공정위 의결문·대법원 판례 ============

def crawl_casenote(out_root: Path, max_items: int = 50) -> int:
    """casenote.kr 공정위 의결 + 대법원 행정판례."""
    out_dir = out_root / "casenote"
    sess = _session()
    base = "https://casenote.kr"
    saved = 0

    # 공정위 + 대법원 검색어
    queries = [
        ("공정거래위원회", "약관"),
        ("공정거래위원회", "불공정거래"),
        ("대법원", "재량권 일탈"),
        ("대법원", "처분이유"),
        ("대법원", "비례원칙"),
        ("대법원", "허가 취소"),
    ]
    for court, q in queries:
        if saved >= max_items:
            break
        try:
            r = sess.get(f"{base}/search", params={"q": f"{court} {q}"}, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(f"  [casenote] '{court} {q}' 실패: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.select("a[href*='/'][href*='판례'], a.title")[:10]:
            href = link.get("href", "")
            detail_url = urljoin(base, href)
            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception:
                continue
            dsoup = BeautifulSoup(d.text, "html.parser")
            title = link.get_text(strip=True)
            content = dsoup.select_one(".case_content, article, .judgment-body")
            text = content.get_text("\n", strip=True) if content else dsoup.get_text("\n", strip=True)
            name = f"{_slug(title)}_{_hash(detail_url)}"
            md = f"# {title}\n\n출처: {detail_url}\n검색어: {court} {q}\n\n---\n\n{text}"
            _save(out_dir, name, md, {
                "source": "casenote",
                "title": title,
                "query": f"{court} {q}",
                "url": detail_url,
                "crawled_at": datetime.now().isoformat(),
            })
            saved += 1
            print(f"  [casenote] saved ({saved}): {title[:60]}")
            time.sleep(SLEEP)
            if saved >= max_items:
                break
    return saved


# ============ 6. 법제처 법령해석 ============

def crawl_moleg_interp(out_root: Path, max_items: int = 30) -> int:
    """법제처 법령해석 사례 — 위임 명확성·재량 해석례."""
    out_dir = out_root / "moleg_interp"
    sess = _session()
    base = "https://www.moleg.go.kr"
    list_url = f"{base}/lawinfo/nwLwAnList.mo"
    saved = 0

    for page in range(1, 6):
        if saved >= max_items:
            break
        try:
            r = sess.get(list_url, params={"mid": "a10106020000", "currentPage": str(page)}, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(f"  [moleg] page {page} 실패: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.select("a[href*='nwLwAnInfo']"):
            href = link.get("href", "")
            detail_url = urljoin(base, href)
            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception:
                continue
            dsoup = BeautifulSoup(d.text, "html.parser")
            title = (dsoup.title.string if dsoup.title else link.get_text(strip=True)) or "untitled"
            text = dsoup.get_text("\n", strip=True)
            name = f"{_slug(title)}_{_hash(detail_url)}"
            md = f"# {title}\n\n출처: {detail_url}\n\n---\n\n{text}"
            _save(out_dir, name, md, {
                "source": "moleg_interp",
                "title": title,
                "url": detail_url,
                "crawled_at": datetime.now().isoformat(),
            })
            saved += 1
            print(f"  [moleg] saved ({saved}): {title[:60]}")
            time.sleep(SLEEP)
            if saved >= max_items:
                break
    return saved


# ============ 7. 금감원 제재공시 ============

def crawl_fss(out_root: Path, max_items: int = 30) -> int:
    """금융감독원 제재공시 — 검사·제재 결과."""
    out_dir = out_root / "fss"
    sess = _session()
    base = "https://www.fss.or.kr"
    list_url = f"{base}/fss/job/openInfo/list.do"
    saved = 0

    for page in range(1, 6):
        if saved >= max_items:
            break
        try:
            r = sess.get(list_url, params={"menuNo": "200476", "pageIndex": str(page)}, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(f"  [fss] page {page} 실패: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.select("a[href*='view']")[:10]:
            href = link.get("href", "")
            detail_url = urljoin(base, href)
            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception:
                continue
            dsoup = BeautifulSoup(d.text, "html.parser")
            title = (dsoup.title.string if dsoup.title else link.get_text(strip=True)) or "untitled"
            text = dsoup.get_text("\n", strip=True)
            name = f"{_slug(title)}_{_hash(detail_url)}"
            md = f"# {title}\n\n출처: {detail_url}\n\n---\n\n{text}"
            _save(out_dir, name, md, {
                "source": "fss",
                "title": title,
                "url": detail_url,
                "crawled_at": datetime.now().isoformat(),
            })
            saved += 1
            print(f"  [fss] saved ({saved}): {title[:60]}")
            time.sleep(SLEEP)
            if saved >= max_items:
                break
    return saved


# ============ main ============

SOURCES = {
    "ftc_press": crawl_ftc_press,
    "ftc_decisions": crawl_ftc_decisions,
    "bai": crawl_bai,
    "korea": crawl_korea_kr,
    "casenote": crawl_casenote,
    "moleg": crawl_moleg_interp,
    "fss": crawl_fss,
}

# 각 소스 list URL — --probe 로 응답성 사전 진단
_PROBE_URLS = {
    "ftc_press": "https://www.ftc.go.kr/www/ReportUserList.do?key=164&rpttype=1",
    "ftc_decisions": "https://case.ftc.go.kr/ocp/co/ltfr.do",
    "bai": "https://www.bai.go.kr/bai/down/publication/decisionAuditList/",
    "korea": "https://www.korea.kr/search/searchResult.do?query=불공정약관&section=news",
    "casenote": "https://casenote.kr/search?q=공정거래위원회+약관",
    "moleg": "https://www.moleg.go.kr/lawinfo/nwLwAnList.mo?mid=a10106020000",
    "fss": "https://www.fss.or.kr/fss/job/openInfo/list.do?menuNo=200476",
}


def _probe() -> None:
    """각 소스 엔드포인트 응답성 진단 (수집 전 어디가 살아있는지 확인)."""
    sess = _session()
    print("=== 소스 응답성 진단 (HTTP 상태) ===")
    for sid, url in _PROBE_URLS.items():
        try:
            r = sess.get(url, timeout=15)
            ok = "✅ 응답" if r.status_code == 200 else f"⚠️ {r.status_code}"
            print(f"  {sid:<15} {ok}  ({len(r.content)} bytes)")
        except Exception as e:
            print(f"  {sid:<15} ❌ {type(e).__name__}: {str(e)[:60]}")
    print("\n→ ✅ 응답 소스만 --source 로 수집하세요. ⚠️/❌ 는 URL 변경/차단.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="all",
                   help=f"수집 대상: all | {' | '.join(SOURCES)} (콤마 구분 가능)")
    p.add_argument("--max-items", type=int, default=50, help="소스당 최대 수집 건수")
    p.add_argument("--out", type=Path, default=Path("outputs/rule_mining/sources/crawled"),
                   help="저장 디렉터리")
    p.add_argument("--probe", action="store_true",
                   help="수집 전 각 소스 엔드포인트 응답성만 진단")
    args = p.parse_args()

    if args.probe:
        _probe()
        return 0

    args.out.mkdir(parents=True, exist_ok=True)

    if args.source == "all":
        sources = list(SOURCES.keys())
    else:
        sources = [s.strip() for s in args.source.split(",") if s.strip() in SOURCES]
        if not sources:
            print(f"ERROR: unknown source. choices={list(SOURCES)}", file=sys.stderr)
            return 1

    summary = {}
    for s in sources:
        print(f"\n=== {s} 크롤링 시작 (max={args.max_items}) ===")
        try:
            n = SOURCES[s](args.out, max_items=args.max_items)
            summary[s] = n
            print(f"  → {n}건 저장")
        except KeyboardInterrupt:
            print("  중단됨")
            break
        except Exception as e:
            print(f"  실패: {e}")
            summary[s] = 0

    (args.out / "_summary.json").write_text(
        json.dumps({
            "summary": summary,
            "total": sum(summary.values()),
            "completed_at": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n총 {sum(summary.values())}건 수집 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
