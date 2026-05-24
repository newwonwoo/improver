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


def _exists(out_dir: Path, url: str) -> bool:
    """해당 URL 이 이미 저장됐는지 (파일명 끝 _{hash}.md 로 판별) — 이어받기/중복 스킵."""
    if not out_dir.exists():
        return False
    h = _hash(url)
    return any(out_dir.glob(f"*_{h}.md"))


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
        # 실측: 보도자료 상세는 selectBbsNttView.do?key=12 링크 (제목 포함)
        links = soup.select("a[href*='selectBbsNttView.do']")
        # 중복 href 제거
        seen_href = set()
        uniq = []
        for a in links:
            h = a.get("href", "")
            t = a.get_text(strip=True)
            if h and t and h not in seen_href:
                seen_href.add(h)
                uniq.append(a)
        links = uniq
        print(f"  [ftc] page {page}: HTTP {r.status_code} · {len(r.content)}b · 보도링크 {len(links)}개")
        if not links:
            print(f"  [ftc] page {page} 보도링크 없음 — a태그 {len(soup.find_all('a'))}개")
            break

        matched = 0
        for link in links:
            title = link.get_text(strip=True)
            if title and not any(kw in title for kw in keywords):
                continue
            matched += 1
            href = link.get("href", "")
            detail_url = urljoin(r.url, href)  # r.url 기준 (./상대경로 정확 처리)
            if _exists(out_dir, detail_url):
                continue  # 이미 저장됨 — 스킵
            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception as e:
                print(f"  [ftc] 상세 실패: {str(e)[:50]}")
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
        print(f"  [ftc] page {page}: 키워드매칭 {matched}개 (전체 {len(links)}개 중)")
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
            if _exists(out_dir, detail_url):
                continue  # 이미 저장됨 — 스킵

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
    list_url = f"{base}/bai/result/branch/list"  # 사용자 실측: 이 경로가 목록 표시
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
            if _exists(out_dir, detail_url):
                continue  # 이미 저장됨 — 스킵

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
                ext = pdf_url.rsplit(".", 1)[-1]
                pdf_name = f"{_slug(title)}_{_hash(pdf_url)}.{ext}"
                if (out_dir / pdf_name).exists():
                    continue  # 이미 다운로드됨 — 스킵
                try:
                    pdf_r = sess.get(pdf_url, timeout=30)
                    if pdf_r.ok:
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
            if _exists(out_dir, detail_url):
                continue  # 이미 저장됨 — 스킵
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
            if _exists(out_dir, detail_url):
                continue  # 이미 저장됨 — 스킵
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
        # debug 로 확인된 작동 URL: ?mid=... (page1), 이후 &pageIndex=N
        params = {"mid": "a10106020000"}
        if page > 1:
            params["pageIndex"] = str(page)
        try:
            r = sess.get(list_url, params=params, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(f"  [moleg] page {page} 실패: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        cand = soup.select("a[href*='nwLwAnInfo.mo']")
        print(f"  [moleg] page {page}: HTTP {r.status_code} · {len(r.content)}b · 후보 {len(cand)}개")
        if not cand:
            print(f"  [moleg] page {page} 링크 없음 — a태그 {len(soup.find_all('a'))}개")
            break
        for link in cand:
            href = link.get("href", "")
            # href 의 &currentPage 가 HTML 엔티티(¤)로 깨져 400 발생 →
            # 필요한 cs_seq 만 추출해 깨끗한 URL 재구성
            m = re.search(r"cs_seq=(\d+)", href)
            if not m:
                continue
            detail_url = f"{base}/lawinfo/nwLwAnInfo.mo?mid=a10106020000&cs_seq={m.group(1)}"
            if _exists(out_dir, detail_url):
                continue  # 이미 저장됨 — 스킵
            try:
                d = sess.get(detail_url, timeout=15)
                d.raise_for_status()
            except Exception as e:
                print(f"  [moleg] 상세 실패: {str(e)[:50]} | {detail_url[:90]}")
                continue
            dsoup = BeautifulSoup(d.text, "html.parser")
            title = link.get_text(strip=True) or (dsoup.title.string if dsoup.title else "untitled")
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
            if _exists(out_dir, detail_url):
                continue  # 이미 저장됨 — 스킵
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
    "bai": "https://www.bai.go.kr/bai/result/branch/list",
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


def _debug(source: str) -> None:
    """리스트 페이지의 실제 링크 구조 출력 — selector 수정용 진단 (크래시 없음)."""
    if source == "all":
        for sid in _PROBE_URLS:
            _debug(sid)
            print()
        return
    url = _PROBE_URLS.get(source)
    if not url:
        print(f"알 수 없는 소스: {source}. 선택: all | {', '.join(_PROBE_URLS)}")
        return
    sess = _session()
    print(f"=== [{source}] 디버그: {url} ===")
    try:
        r = sess.get(url, timeout=20)
    except Exception as e:
        print(f"❌ 요청 실패: {type(e).__name__}: {str(e)[:80]}")
        print("→ 이 소스는 서버가 Python 접속을 차단(TLS reset). 직접 크롤 불가.")
        return
    print(f"HTTP {r.status_code} · {len(r.content)} bytes")
    soup = BeautifulSoup(r.text, "html.parser")
    anchors = soup.find_all("a")
    print(f"전체 <a> 태그: {len(anchors)}개\n")

    # 상세보기로 보이는 링크 후보 (href/onclick 에 view·seq·no·id·idx·nttId 등)
    import re as _re
    pat = _re.compile(r"(view|seq|[?&]no=|idx|nttId|articleNo|report_data_no|dispNo|nttSn|bbsSn|list_no)", _re.I)
    cand = []
    for a in anchors:
        href = a.get("href") or ""
        onclick = a.get("onclick") or ""
        title = a.get_text(strip=True)
        if pat.search(href) or pat.search(onclick):
            cand.append((href[:70], onclick[:70], title[:35]))
    print(f"상세링크 후보(view/seq/no/id 패턴): {len(cand)}개 — 상위 20:")
    for href, onclick, title in cand[:20]:
        print(f"  href={href!r}")
        if onclick:
            print(f"      onclick={onclick!r}")
        print(f"      title={title!r}")
    if not cand:
        # 후보 없으면 → AJAX 로딩 의심. 테이블/리스트 컨테이너 구조 출력
        print("⚠️ 상세링크 후보 0 — 목록이 JS(AJAX)로 로딩될 가능성.")
        print("페이지 내 table/ul/div[class] 상위 컨테이너:")
        for tag in soup.select("table, ul.board_list, div[class*=list], div[class*=board]")[:8]:
            cls = tag.get("class")
            print(f"  <{tag.name} class={cls}> 자식 {len(tag.find_all('a'))}개 링크")
    print("\n→ 이 출력을 그대로 복사해 보내주세요. selector 정확히 맞춰드립니다.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="all",
                   help=f"수집 대상: all | {' | '.join(SOURCES)} (콤마 구분 가능)")
    p.add_argument("--max-items", type=int, default=50, help="소스당 최대 수집 건수")
    p.add_argument("--debug", metavar="SOURCE",
                   help="해당 소스 리스트 페이지의 실제 링크 구조 출력 (selector 수정용)")
    p.add_argument("--out", type=Path, default=Path("outputs/rule_mining/sources/crawled"),
                   help="저장 디렉터리")
    p.add_argument("--probe", action="store_true",
                   help="수집 전 각 소스 엔드포인트 응답성만 진단")
    args = p.parse_args()

    if args.debug:
        _debug(args.debug)
        return 0

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
