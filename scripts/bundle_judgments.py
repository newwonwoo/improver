#!/usr/bin/env python3
"""1,704개 judgment MD를 400개씩 5번들로 묶기.

각 번들:
- 한 .md 파일 안에 400개 법률의 본법+후보 섹션을 차례로 배치
- 시스템 프롬프트는 번들 최상단에 1회만 (각 법률마다 반복 X)
- 각 법률 사이는 명확한 구분선과 목차 점프 가능한 헤더
- 부록 A(시행령)·B(시행규칙)는 본 번들에서 제외 — 사이즈 안정 + LLM 필요시
  outputs/judgments/<법령명>.md에서 별도 첨부

워크플로:
    1. python scripts/bundle_judgments.py --batch-size 400 --output-dir outputs/bundles
    2. 사용자가 번들 1개씩 5회에 걸쳐 LLM에 입력 (한 번에 한 법률 섹션씩 떼서 호출)
    3. 응답은 outputs/llm_responses/<법령명>.json 으로 저장
    4. import_judgment_batch.py → tune_engine.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.judgment_prompt import SYSTEM_PROMPT, expected_schema_excerpt  # noqa: E402


_APPENDIX_A_MARKER = "## 📑 부록 A — 시행령 전문"
_APPENDIX_B_MARKER = "## 📑 부록 B — 시행규칙 전문"
_SCHEMA_MARKER = "## 🎯 응답 형식 재확인"
_PROMPT_HEADER_MARKER = "## 🤖 LLM 시스템 프롬프트"


def _strip_appendices(text: str) -> str:
    """본법 + 후보 finding 부분만 남기고 부록·스키마 제거."""
    for marker in (_APPENDIX_A_MARKER, _APPENDIX_B_MARKER, _SCHEMA_MARKER):
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.rstrip()


def _strip_header_prompt(text: str) -> str:
    """번들 최상단에 시스템 프롬프트가 한 번만 등장하도록 각 법률 섹션의 헤더 블록 제거.

    헤더 시작("<!--" 또는 "## 🤖 LLM 시스템 프롬프트") ~ 첫 "## 메타" 직전까지 제거.
    """
    meta_idx = text.find("## 메타")
    if meta_idx == -1:
        return text
    # 첫 줄에 "# 「법령명」 LLM 판단용 자료"는 보존
    first_newline = text.find("\n")
    if first_newline == -1:
        return text
    return text[: first_newline + 1] + "\n" + text[meta_idx:]


def _bundle_header(idx: int, total: int, law_count: int, start_law: str, end_law: str) -> str:
    return f"""# 📦 LLM 판단용 묶음 번들 {idx}/{total}

> **이 번들 안 법령 수**: {law_count}개
> **범위**: 「{start_law}」 ~ 「{end_law}」
>
> **사용 방법**:
> 1. 아래 "🤖 LLM 시스템 프롬프트" 블록을 LLM 시스템 프롬프트로 1회 설정
> 2. 번들 안의 각 법령 섹션(`# 「<법령명>」 LLM 판단용 자료`로 시작)을 **하나씩** 떼서
>    LLM에 입력 → JSON 응답 받음
> 3. 응답을 `outputs/llm_responses/<법령명>.json`으로 저장
> 4. 5개 번들 모두 처리 후 `scripts/import_judgment_batch.py` + `scripts/tune_engine.py` 실행
>
> **시행령·시행규칙이 필요한 경우** (예: S-02 위임 검증을 정밀하게 하려면):
> `outputs/judgments/<법령명>.md` 에서 부록 A/B를 떼서 LLM 메시지에 함께 첨부.

---

## 🤖 LLM 시스템 프롬프트 (이 번들 전체 공통)

```
{SYSTEM_PROMPT}
```

---

{expected_schema_excerpt()}

---

# 📋 이 번들의 법령 목록

"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="judgment MD를 400개씩 번들로 묶기")
    parser.add_argument("--input-dir", default="outputs/judgments")
    parser.add_argument("--output-dir", default="outputs/bundles")
    parser.add_argument("--batch-size", type=int, default=400)
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("*.md"))
    if not files:
        print(f"입력 디렉토리에 .md 파일 없음: {input_dir}", file=sys.stderr)
        return 1

    n = len(files)
    bs = args.batch_size
    total_bundles = (n + bs - 1) // bs

    for b in range(total_bundles):
        chunk = files[b * bs: (b + 1) * bs]
        toc_lines: list[str] = []
        body_lines: list[str] = []
        for i, p in enumerate(chunk, 1):
            law_name = p.stem
            toc_lines.append(f"{i}. [「{law_name}」](#{law_name})")
            raw = p.read_text(encoding="utf-8")
            core = _strip_appendices(raw)
            core = _strip_header_prompt(core)
            body_lines.append("\n\n---\n\n")
            body_lines.append(f'<a id="{law_name}"></a>')
            body_lines.append("")
            body_lines.append(core.strip())

        header = _bundle_header(
            idx=b + 1, total=total_bundles, law_count=len(chunk),
            start_law=chunk[0].stem, end_law=chunk[-1].stem,
        )
        content = header + "\n".join(toc_lines) + "\n\n" + "\n".join(body_lines) + "\n"
        out_path = output_dir / f"bundle_{b + 1:02d}_of_{total_bundles:02d}.md"
        out_path.write_text(content, encoding="utf-8")
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(
            f"번들 {b + 1}/{total_bundles}: {len(chunk)}개 법률, "
            f"{size_mb:.1f}MB, 「{chunk[0].stem[:20]}」~「{chunk[-1].stem[:20]}」 → {out_path}",
            file=sys.stderr,
        )

    print(f"\n총 {total_bundles}개 번들 생성 완료.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
