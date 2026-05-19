"""G-01 예외·단서 (설계서 §3.2 G-01).

항별로 단서(다만) 카운팅 — 다항 조문은 항당 최대 1개가 정상.
"""
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


def _max_danseo_per_para(art: Article) -> int:
    """단일 항에서 최대 단서(다만) 수. 다항 조문에서 항별 집계로 오탐 감소."""
    if art.paragraphs:
        para_texts = [p.text for p in art.paragraphs if p.text.strip()]
        if para_texts:
            return max(len(_DANSEO.findall(pt)) for pt in para_texts)
    return len(_DANSEO.findall(art.full_text))


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
            # 항별 최대 단서 수로 평가 (다항 조문의 항당 1개 단서는 정상)
            danseo_count = _max_danseo_per_para(art)
            has_vague_exc = bool(_VAGUE_EXC.search(text))
            has_disposition = bool(_DISPOSITION_KEY.search(text))

            if danseo_count >= 4:
                severity = "심각"
            elif danseo_count >= 3:
                severity = "경고"
            elif danseo_count == 2 and has_vague_exc:
                severity = "경고"
            elif danseo_count == 2:
                severity = "주의"
            elif danseo_count == 1 and has_vague_exc and has_disposition:
                severity = "주의"
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
                        matched_text=f"단서 {danseo_count}회 (한 항 내)",
                        summary=f"단서 {danseo_count}회 중첩 (단일 항)"
                        + (" + 포괄 예외" if has_vague_exc else ""),
                        fix_type="replace",
                    ),
                )
            )
        return findings
