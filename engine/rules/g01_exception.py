"""G-01 예외·단서 (설계서 §3.2 G-01)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_DANSEO = re.compile(r"다만[,\s]")
_VAGUE_EXC = re.compile(r"대통령령으로 정하는 (경우|사항)을? 제외")
# FP 필터: 면책·양벌 단서 (고의·중과실 면책은 적법 패턴)
_EXEMPT_DANSEO = re.compile(r"(상당한\s*주의와\s*감독|고의가\s*아닌|정상적인\s*인식능력|고의\s*또는\s*과실이\s*없)")
# TP 부스트: 처분조 단서 중첩
_DISPOSITION_KEY = re.compile(r"(취소|정지|명령|과징금|해임|폐쇄)")


class G01Exception:
    pattern_id = "G-01"
    pattern_name = "예외·단서"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            # FP 필터: 정의·벌칙·목적 조문
            if art.is_definition() or art.is_penalty() or art.is_purpose():
                continue
            text = art.full_text
            # FP 필터: 면책·양벌 단서 (고의·중과실 예외 명시 = 적법 패턴)
            if _EXEMPT_DANSEO.search(text):
                continue
            danseo_count = len(_DANSEO.findall(text))
            has_vague_exc = bool(_VAGUE_EXC.search(text))

            has_disposition = bool(_DISPOSITION_KEY.search(text))
            if danseo_count >= 3:
                severity = "심각"
            elif danseo_count == 2:
                severity = "경고"
            elif danseo_count == 1 and has_vague_exc:
                severity = "주의"
            elif danseo_count == 1 and has_disposition and has_vague_exc:
                # 처분조 + 포괄예외 단서 1개도 경고 수준
                severity = "경고"
            else:
                continue
            # TP 부스트: 처분조 단서 중첩은 한 단계 상향
            if has_disposition and severity in ("주의", "개선"):
                severity = "경고"

            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"단서 {danseo_count}회",
                        summary=f"단서 {danseo_count}회 중첩"
                        + (" + 포괄 예외" if has_vague_exc else ""),
                        fix_type="replace",
                    ),
                )
            )
        return findings
