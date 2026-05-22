# 룰 마이닝 크롤러 사용 안내

샌드박스 환경에서는 한국 정부 사이트(law.go.kr, ftc.go.kr, bai.go.kr 등) 가 모두 403 차단입니다. 따라서 크롤러는 **사용자 본인의 로컬 환경에서 실행**해야 합니다.

## 설치

```bash
pip install requests beautifulsoup4
```

## 사용법

```bash
# 전체 7개 소스 크롤링 (각 50건씩)
python scripts/crawl_rule_sources.py --source all --max-items 50

# 공정위만
python scripts/crawl_rule_sources.py --source ftc_press,ftc_decisions

# 감사원 + 권익위 + 정책브리핑
python scripts/crawl_rule_sources.py --source bai,korea --max-items 100
```

## 수집 대상 (7개 소스)

| 소스 ID | 대상 사이트 | 내용 |
|---------|-----------|------|
| `ftc_press` | ftc.go.kr | 공정위 보도자료 (약관·시정명령 키워드 필터) |
| `ftc_decisions` | case.ftc.go.kr | 공정위 의결서 (약관 검색) |
| `bai` | bai.go.kr | 감사원 감사결과 (PDF 자동 다운로드) |
| `korea` | korea.kr | 정책브리핑 (감사원·공정위·권익위·금감원 통합) |
| `casenote` | casenote.kr | 공정위 의결문 + 대법원 행정판례 |
| `moleg` | moleg.go.kr | 법제처 법령해석 사례 |
| `fss` | fss.or.kr | 금감원 제재공시 |

## 저장 구조

```
outputs/rule_mining/sources/crawled/
├── ftc_press/
│   ├── 2025-10-29_은행_상호저축은행_불공정약관_시정_<hash>.md
│   └── 2025-10-29_은행_상호저축은행_불공정약관_시정_<hash>.json   # 메타
├── ftc_decisions/
│   └── ...
├── bai/
│   ├── 통계조작_감사결과_<hash>.md
│   └── 통계조작_감사결과_<hash>.pdf     # 첨부 PDF 자동 다운로드
├── korea_kr/
├── casenote/
├── moleg_interp/
├── fss/
└── _summary.json
```

## 예상 수집량

| 소스 | 1회 실행 (max=50) | 예상 시간 |
|------|------------------|----------|
| ftc_press | ~30건 | 3분 |
| ftc_decisions | ~50건 | 5분 |
| bai | ~30건 + PDF | 5분 |
| korea | ~50건 | 5분 |
| casenote | ~50건 | 5분 |
| moleg | ~30건 | 3분 |
| fss | ~30건 | 3분 |
| **합계** | **270건** | **30분** |

## 수집 후 활용

1. 수집된 자료를 살펴서 가치 있는 케이스 선별
2. `outputs/rule_mining/_ALL_IN_ONE_PROMPT.md` 끝에 첨부
3. Claude.ai 웹에 통째 붙여넣기 → 50~100개 신규 룰 응답
4. 응답 JSON을 `outputs/rule_mining/responses/` 로 저장
5. (향후) import 스크립트가 자동으로 `engine/rules/` 에 룰 생성

## 주의사항

- **서버 부하**: 요청 간 1초 대기 (SLEEP=1.0)
- **User-Agent**: Chrome 120 위장 (Bot 차단 회피)
- **반복 실행**: 동일 URL은 hash 기반으로 중복 방지
- **로봇배제표준**: 각 사이트의 robots.txt 확인 권장
- **저작권**: 수집 자료는 룰 마이닝 연구 목적으로만 활용

## 사이트 구조 변경 대응

각 사이트의 HTML 구조가 변경되면 selector 수정이 필요합니다.
`scripts/crawl_rule_sources.py` 내 각 함수의 `.select()` 부분을 확인하세요:

- `crawl_ftc_press`: `table.board_list tbody tr`, `li.board_li`
- `crawl_bai`: `li, tr`
- `crawl_casenote`: `a[href*='/'][href*='판례']`
- `crawl_moleg_interp`: `a[href*='nwLwAnInfo']`

기능 확장 (예: 새 사이트 추가) 시 `SOURCES` dict 에 등록만 하면 됩니다.

---

## 1차 권장 실행

```bash
# 1. 공정위·정책브리핑 우선 수집 (가장 자료 풍부)
python scripts/crawl_rule_sources.py --source ftc_press,korea --max-items 100

# 2. 감사원 PDF 수집 (시간 소요)
python scripts/crawl_rule_sources.py --source bai --max-items 30

# 3. 대법원 판례·법제처 해석
python scripts/crawl_rule_sources.py --source casenote,moleg --max-items 50
```

수집 완료 후 `outputs/rule_mining/sources/crawled/_summary.json` 확인.
