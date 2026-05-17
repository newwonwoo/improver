# 규정개선 분석기 (Regulation Improvement Analyzer)

법령 텍스트를 넣으면 자동으로 문제점을 찾고, 등급을 매기고, 고치는 방법까지 알려주는 엔진

---

## 프로젝트 구조

```
improver/
├── docs/design/              # 설계서
│   ├── phase1_core_design_v2.md      # 핵심 설계서 (등급산출, 권고안, 리포트)
│   ├── phase1_engine_design.md       # 엔진 설계서 (입력, 파서, 룰스캔, LLM, DB)
│   ├── subcategory_deep_design_v2.md # 서브체크 84개 상세 + 사유 정의
│   ├── gap_analysis_patterns_v2.md   # 산출물 Gap 분석 + 리포트 패턴 P-01~P-10
│   ├── pattern_inventory.md          # 1,691개 법률 전수분석 패턴별 결과
│   └── design_changelog_v2.md        # 설계 변경 이력
│
├── data/
│   ├── scan_results/                 # 전수 분석 결과
│   │   ├── full_analysis.json        # 65,607건 패턴별 분포 + 오탐률
│   │   ├── batch_scan_result.json    # 1,691개 법률 등급 + Top 20
│   │   ├── delegation_match.json     # 35,651건 위임-시행령 매칭
│   │   └── scan_result.json          # 개별 스캔 결과
│   │
│   └── patterns/                     # 패턴 상세 데이터
│       ├── deep_patterns.json        # G-04 내부통제, E-05 제재공백 심층
│       ├── all_patterns_deep.json    # 전 패턴 심층 분석
│       ├── deleg_pattern.json        # 위임 패턴 상세
│       └── remaining_patterns.json   # F-03, G-01, G-02, E-04 등 상세
│
├── reference/
│   └── housing_fund_report_v3.jsx    # 주택도시기금법 리포트 프로토타입
│
└── README.md
```

## 엔진 파이프라인

```
[입력] → [조문파서] → [룰스캔18] → [AI판단3] → [DB검증2] → [등급산출] → [권고안] → [리포트]
```

## 핵심 숫자

| 항목 | 값 |
|------|-----|
| 분석 대상 | 1,691개 법률 |
| 패턴 | 22개 (84 서브체크) |
| 전수 분석 | 65,607건 |
| 위임 매칭 | 35,651건 (92% 이행) |
| 등급 체계 | A~F 5단계 |
| 권고안 템플릿 | 23×5 = 115개 |
| 리포트 패턴 | P-01~P-10 |

## 개발 방식

- Phase 1: 클로드 아티팩트 (React)
- Phase 2: 독립 웹사이트 배포
