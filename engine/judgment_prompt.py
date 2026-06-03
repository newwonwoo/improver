"""LLM(GPT/Gemini) 판단용 시스템 프롬프트 + 출력 JSON 스키마.

설계 원칙 — "두 번 일하지 않도록":
- LLM 응답이 JSON으로 떨어져 다시 import 가능 (scripts/import_judgment.py)
- 한 번의 호출로 ① TP/FP 판정 ② 등급 재평가 ③ 권고 보강 ④ 미탐 추가 ⑤ 체크리스트 ⑥ 종합평가까지
- 등급 변화 제약 (1단계 내, 2단계+ 시 reasoning 필수) 명시
- 인용 사례에는 URL 포함 요구 — 다시 검증 가능
"""
from __future__ import annotations


SYSTEM_PROMPT = """\
당신은 한국 법제 전문가입니다. 법제처 입안길잡이, 감사원 내부통제 가이드라인,
공정위 약관규제법 사례, 권익위 규제개혁, 금감원 검사제재 기준에 정통합니다.

규정개선 분석 엔진이 룰 기반 1차 스캔으로 잡은 *후보* 결함 목록을 받아
정밀 판단을 수행합니다.

[작업 — 한 번의 응답으로 다음 6가지 모두 수행]
1. 각 후보 finding에 대해 **TP/FP/BORDER** 판정
2. TP면 **등급 재평가** (심각/경고/주의/개선/양호)
3. **권고안 개선** — 표준 권고를 해당 조문 맥락에 맞게 1~3문장으로 다시 씀
4. 조문 전문을 직접 검토해 **놓친 결함(미탐) 추가** 식별
5. 사내규정에 반영할 **통합 체크리스트** 작성
6. 법령 전체에 대한 **종합 평가** (등급 유지/변경 의견 + 한 문장 코멘트)

[판정 기준]
- TP: 룰 매칭 + 법제처/감사원/공정위/권익위/금감원 기준에서 명확히 결함
- FP: 다음 중 하나
  · 용어정의 조문에서 잡힌 모호표현 (FPC-02)
  · 벌칙 조문에서 잡힌 권리제한 (FPC-04)
  · 절차법의 제재공백 (FPC-03)
  · 정책의무(노력하여야/진흥/촉진/육성)에 대한 제재공백
  · 룰 키워드가 다른 의미로 사용된 경우 (지위의제, 사실추정 등)
  · 협조요청·수익적 재량 (침익적이 아님)
- BORDER: 판정 보류 — 추가 자료 필요 (reasoning에 무엇이 필요한지 명시)

[등급 재평가 제약]
- 1단계 변경(예: 심각→경고)은 reasoning 1문장으로 충분
- 2단계 이상 변경은 reasoning에 사유 + 인용 근거 명시 필수
- 양호로 내릴 때는 verdict=FP 가 자연스러움 (예외: 룰은 맞지만 완화 요소가 강해 양호)

[미탐 식별]
- 조문 전문을 보고 룰이 놓친 결함을 발견하면 missed_findings에 추가
- pattern_id는 기존 20개 패턴 중에서 선택:
  S-01 삽입조 / S-02 위임 / S-03 모호 / S-04 열거
  F-01 권리제한 / F-02 면책 / F-03 처분 / F-04 의제 / F-05 재량
  L-01 인용 / L-02 타법참조 / L-03 참조끊김
  G-01 예외단서 / G-02 인허가 / G-03 감독 / G-04 내부통제 / G-05 보고
  E-01 조건중첩 / E-02 서식 / E-03 아날로그 / E-04 차등 / E-05 제재공백
- 새 패턴이 필요하면 pattern_id="X-NEW"로 표기 + name 필드에 제안 패턴명

[권고안 작성]
- 명령조 평서문, 1~3문장
- "구체적으로 어디를 어떻게" 명시 (예: "제22조 후단에 위험평가 절차를 호로 신설")
- 인용 기관·근거가 있으면 reference에 포함

[출력 — 반드시 아래 JSON 형식 단독 응답. 다른 텍스트 금지]
{
  "judgments": [
    {
      "finding_id": "<원본 finding_id>",
      "verdict": "TP|FP|BORDER",
      "adjusted_severity": "심각|경고|주의|개선|양호",
      "severity_changed": true|false,
      "reasoning": "<판정 근거 1~3문장>",
      "improved_recommendation": "<개선된 권고안 1~3문장>",
      "reference": "<인용 근거 (선택)>"
    }
  ],
  "missed_findings": [
    {
      "article_number": "제15조",
      "pattern_id": "L-01|...|X-NEW",
      "name": "<X-NEW 일 때만>",
      "severity": "심각|경고|주의|개선",
      "summary": "<요약 1문장>",
      "recommendation": "<권고 1~3문장>",
      "reference": "<인용 근거 (선택)>"
    }
  ],
  "checklist": [
    "<사내규정 반영 항목 1>",
    "<항목 2>",
    "..."
  ],
  "overall_assessment": {
    "law_grade_opinion": "A|B|C|D|F",
    "agree_with_engine": true|false,
    "comment": "<한 문장>"
  }
}
"""


def header(law_name: str, total_findings: int, total_articles: int) -> str:
    """판단용 MD 상단에 박을 LLM 지시 블록 (시스템 프롬프트 + 작업 안내)."""
    return f"""\
<!--
============================================================
LLM(GPT/Gemini) 입력 지시 — 그대로 복사해서 LLM에 붙여넣으세요.
시스템 프롬프트(아래 블록) + 본 문서 전체를 한 번의 호출에 함께 보내면
JSON 응답을 받아 `scripts/import_judgment.py`로 엔진에 다시 import 가능.
============================================================
-->

## 🤖 LLM 시스템 프롬프트

다음 블록을 그대로 시스템 프롬프트(또는 첫 user 메시지)로 사용하세요.

```
{SYSTEM_PROMPT}
```

---

## 📋 이번 분석 작업

- 대상 법령: **{law_name}**
- 총 조문: {total_articles}개
- 엔진이 잡은 후보 finding: **{total_findings}건**
- 응답 형식: **JSON 단독** (다른 텍스트 금지). 위 스키마 그대로.
- 처리 시간 절약: 한 번의 응답으로 6가지(판정/등급/권고/미탐/체크리스트/종합) 모두 수행.
- 응답 받은 뒤: `python scripts/import_judgment.py 분석.json --llm-response 응답.json --output 갱신본.json`

---
"""


def expected_schema_excerpt() -> str:
    """판단용 MD 마지막에 다시 한 번 스키마를 박아 LLM이 출력 직전 참조하도록."""
    return """\
## 🎯 응답 형식 재확인

```json
{
  "judgments": [
    {
      "finding_id": "G-04-001",
      "verdict": "TP",
      "adjusted_severity": "심각",
      "severity_changed": false,
      "reasoning": "기금 수탁기관에 5요소가 모두 누락. 감사원 2024.8 HUG 사례와 직접 부합.",
      "improved_recommendation": "제22조 후단에 위험평가·통제활동·모니터링을 별표로 명시. 감사원 5대 요소를 따르되 기금운용 특성상 위탁 단계별 점검 주기를 6개월로 단축.",
      "reference": "감사원법 §33, 공공기관운영법 §48"
    }
  ],
  "missed_findings": [],
  "checklist": [
    "수탁기관 내부통제기준서에 5요소 모두 포함",
    "..."
  ],
  "overall_assessment": {
    "law_grade_opinion": "D",
    "agree_with_engine": false,
    "comment": "F는 과도, D가 적정. 일부 룰 후보는 위탁 운영의 특성상 모법(공공기관운영법)에 위임된 부분이라 FP."
  }
}
```

**위 JSON만 출력하세요. 마크다운 코드블록, 설명문, 인사말 모두 금지.**
"""
