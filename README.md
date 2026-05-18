# 규정개선 분석기 (Regulation Improvement Analyzer)

법령 텍스트를 넣으면 자동으로 문제점을 찾고, 등급을 매기고, 고치는 방법까지 알려주는 엔진.

---

## 엔진 강화 워크플로 (LLM 피드백 루프)

```
[1] 모든 법령 분석 → judgment MD (시행령 부록 포함)
    python scripts/analyze_batch_sets.py data/laws/raw --output-dir outputs/

[2] 각 MD를 GPT/Gemini에 입력 → JSON 응답 받아 outputs/llm_responses/<법령명>.json 저장
    (MD 안에 시스템 프롬프트 + JSON 스키마가 모두 박혀 있어 한 번 호출로 6가지 작업 완료:
     TP/FP 판정 / 등급 재평가 / 권고안 개선 / 미탐 식별 / 체크리스트 / 종합평가)

[3] LLM 응답을 결과에 일괄 import
    python scripts/import_judgment_batch.py \
        --results-dir outputs/results \
        --llm-dir outputs/llm_responses \
        --output-dir outputs/results_with_llm

[4] LLM 응답을 집계해 엔진 튜닝 제안 생성
    python scripts/tune_engine.py \
        --llm-dir outputs/llm_responses \
        --output outputs/tuning_proposals.json
    # → FP 비율 ≥40% 패턴 / 등급 시프트 큰 패턴 / X-NEW 새 룰 후보 식별

[5] 사람이 검토해 config/patterns.json, recommendations.json 갱신 → 룰 정밀도↑
```

데이터 위치:
- 로데이터: `data/laws/raw/<법령명>/{법률,시행령,시행규칙}.md` — legalize-kr 1,720 세트
- 판단용 MD: `outputs/judgments/<법령명>.md` — 시행령 부록 + 위임 매핑 인라인
- 분석 JSON: `outputs/results/<법령명>.json` — `.gitignore` (재생성 가능)
- 튜닝 제안: `outputs/tuning_proposals.json`

---

## 빠른 시작

```bash
# 의존성
pip install -r requirements.txt

# 단일 법령 분석 (JSON + HTML)
python scripts/analyze.py fixtures/synthetic_housing_fund.txt \
    --name "주택도시기금법" --category 공공기관법 \
    --output result.json --html report.html

# LLM 정밀 판단 + Layer 3 권고안 (ANTHROPIC_API_KEY 필요, 없으면 MockClient)
python scripts/analyze.py <법령.txt> --name "<법령명>" --use-llm \
    --llm-log llm_calls.jsonl

# 디렉토리 일괄 분석
python scripts/analyze_batch.py laws/ --output-dir results/ --workers 4

# 정밀도 평가 (골드셋)
python scripts/evaluate.py --goldset data/goldset/synthetic_housing_fund.json \
    --laws-dir fixtures/

# 법령 인덱스 빌드 (MCP용)
python scripts/build_index.py <법령_텍스트_디렉토리> \
    --output data/indexes/law_index.json

# HTTP 서버 (fastapi/uvicorn 필요)
pip install fastapi uvicorn pydantic
python scripts/serve.py --port 8080
# → POST /analyze, GET /patterns, GET /agencies, GET /healthz

# React 리포트
cd web && npm install && npm run build  # dist/index.html
```

---

## 엔진 파이프라인

```
[입력] → [조문파서] → [룰스캔20] → [LLM판단3] → [MCP검증2] → [등급산출] → [권고안 L1/L2/L3] → [리포트]
                                                                                          ↓
                                                                              교차 패턴 권고안 +
                                                                              체크리스트 + 로드맵
```

---

## 디렉토리 구조

```
improver/
├── engine/                       # 엔진 코어
│   ├── schema.py                 # Law / Article / Finding / AnalysisResult
│   ├── parser.py                 # 조/항/호/목 4계층 파서
│   ├── severity.py               # 등급 ↔ 점수 + 임계치 (A~F)
│   ├── scorer.py                 # Finding→Article→Law 3계층 점수
│   ├── recommender.py            # Layer 1 표준 권고안
│   ├── cases.py                  # Layer 2 사례 + 기관 매핑
│   ├── cross_pattern.py          # 교차 패턴 권고안 (3패턴↑ 동일 조문)
│   ├── fpc.py                    # 오탐 보정 (절차법 등급 하향)
│   ├── html_report.py            # 정적 HTML 리포트
│   ├── api.py                    # FastAPI 라우트
│   ├── rules/                    # 20개 룰 패턴
│   │   ├── s01_insertion … s04_enumeration
│   │   ├── f01_rights … f05_discretion
│   │   ├── l01_citation, l02_cross_ref, l03_broken_ref
│   │   ├── g01_exception … g05_report
│   │   └── e01_conditions … e05_sanction
│   ├── mcp/                      # 법령 DB 연동
│   │   ├── db.py                 # LawIndex + check_article_exists / check_enforcement_decree
│   │   └── lawkr_api.py          # 법제처 API fallback (캐시 + 쿼터)
│   ├── llm/                      # LLM 진단 엔진
│   │   ├── client.py             # Anthropic + Mock + 호출 로그
│   │   ├── prompts.py            # F-04/F-05/E-05 시스템 프롬프트
│   │   ├── judge.py              # 룰 후보 → LLM 등급 조정
│   │   └── recommender_layer3.py # Layer 3 맞춤 권고안
│   └── phase2/                   # 사내규정 비교 (위법유형 5종)
│       ├── requirements.py       # 서브체크 → 요구사항
│       └── compare.py            # 누락/축소/초과/불일치/미갱신 판정
│
├── config/                       # 설정·사전
│   ├── engine.json               # 엔진 동작
│   ├── recommendations.json      # 100개 권고안 템플릿 (20×5)
│   ├── disciplinary_cases.json   # 8건 제재 사례 DB (Layer 2)
│   ├── sub_check_agencies.json   # 31개 서브체크 → 기관
│   ├── short_names.json          # 법령 약칭
│   ├── industry.json             # 6개 산업군 + 가중치
│   └── type_keywords.json        # E-04 유형별 차등 사전
│
├── data/
│   ├── indexes/                  # MCP 로컬 인덱스
│   ├── scan_results/             # Phase 0 전수 분석 결과
│   ├── patterns/                 # 패턴 통계
│   └── goldset/                  # 정밀도 평가 골드셋
│
├── docs/design/                  # 설계서 6종
├── scripts/
│   ├── analyze.py                # 단일 분석 CLI
│   ├── analyze_batch.py          # 일괄 분석 CLI
│   ├── evaluate.py               # 골드셋 평가
│   ├── build_index.py            # 법령 인덱스 빌더
│   └── serve.py                  # HTTP 서버
├── tests/                        # pytest 100+
├── web/                          # React 리포트 (Vite)
├── fixtures/                     # 합성 법령 텍스트
└── reference/                    # 원본 프로토타입
```

---

## 핵심 숫자

| 항목 | 값 |
|------|-----|
| 분석 대상 | 1,691개 법률 (전수 데이터) |
| 룰 패턴 | 20개 (S/F/L/G/E) |
| 서브체크 | 84개 (현재 30+ 매핑) |
| 권고안 템플릿 | 100개 (20×5) |
| 사례 DB | 8건 (확장 중) |
| 리포트 패턴 | P-01~P-10 (HTML/React 양쪽) |
| 등급 체계 | A~F (5단계, Finding→Article→Law) |
| 위법유형 (Phase 2) | 5종 (누락/축소/초과/불일치/미갱신) |
| LLM 비용 | Sonnet ~$0.50 / Flash ~$0.05 (법령 1건) |

---

## 개발 단계

| Phase | 상태 | 내용 |
|-------|------|------|
| Phase 0 | ✅ | 전수 데이터 수집 + 패턴 발굴 |
| Phase 1 | ✅ | 엔진 코어 + 룰 20 + LLM + MCP + 리포트 |
| Phase 2 | 🚧 | 사내규정 비교 (요구사항 추출기까지) |
| Phase 3 | 📐 | 산업별 가중치 + 다국어 |

---

## CLI 옵션 요약

| 옵션 | 설명 |
|------|------|
| `--name` | 법령명 (필수) |
| `--law-type` | 법률/대통령령/부령 (기본 "법률") |
| `--category` | 금융법/공공기관법/민사법/절차법/일반 (미지정 시 자동) |
| `--output` | JSON 출력 경로 (기본 stdout) |
| `--html` | 정적 HTML 리포트 출력 |
| `--use-llm` | LLM 정밀 판단 + Layer 3 권고안 |
| `--llm-log` | LLM 호출 로그 JSONL 출력 |
| `--no-cross-pattern` | 교차 패턴 권고안 비활성화 |
