#!/usr/bin/env python3
"""거대 judgment MD를 LLM 컨텍스트에 맞게 분할.

사용법:
    # 한 개 분할
    python scripts/split_judgment.py outputs/judgments/약사법.md \\
        --mode appendix --output-dir outputs/chunks/

    # 전체 자동 분할 (큰 것만)
    python scripts/split_judgment.py outputs/judgments/ \\
        --mode auto --max-kb 200 --output-dir outputs/chunks/

분할 모드:
    appendix : 본법 / 시행령 부록 / 시행규칙 부록 3분할 (가장 자연스러움)
    chapter  : 조문 범위로 분할 (--chunks N)
    auto     : 파일 크기에 따라 자동 선택

각 분할 파트는 LLM 프롬프트 + 응답 스키마를 그대로 갖고 있어 독립 실행 가능.
응답 받은 뒤 import_judgment.py 또는 import_judgment_batch.py로 다시 합치면 됨.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.judgment_prompt import expected_schema_excerpt, header  # noqa: E402


_APPENDIX_A = "## 📑 부록 A — 시행령 전문"
_APPENDIX_B = "## 📑 부록 B — 시행규칙 전문"
_SCHEMA_MARKER = "## 🎯 응답 형식 재확인"


def _split_at(text: str, marker: str) -> tuple[str, str]:
    idx = text.find(marker)
    if idx == -1:
        return text, ""
    return text[:idx].rstrip(), text[idx:]


def _build_part_header(law_name: str, part_label: str, total_parts: int, part_idx: int,
                        is_main: bool = False) -> str:
    return f"""# 「{law_name}」 LLM 판단용 자료 — {part_label} ({part_idx}/{total_parts})

> **분할 안내** — 이 문서는 거대 법령을 LLM 컨텍스트 한계에 맞게 분할한 {part_idx}번째 파트입니다.
> 다른 파트에도 동일한 시스템 프롬프트가 박혀 있습니다.
> 응답은 각 파트별로 독립 JSON으로 받아 `scripts/import_judgment_batch.py`로 일괄 import하면 됩니다.

{"" if is_main else "이 파트는 첫 파트의 메타·요약·후보 finding을 다시 한 번 참고할 수 있도록 LLM이 함께 보길 권장합니다."}

"""


def split_appendix_mode(md_path: Path, output_dir: Path) -> list[Path]:
    """본법 (메타+후보+조문) / 시행령 부록 / 시행규칙 부록 3분할."""
    text = md_path.read_text(encoding="utf-8")
    name = md_path.stem

    # 부록 위치 식별
    main_part, rest = _split_at(text, _APPENDIX_A)
    if not rest:
        main_part, rest = _split_at(text, _APPENDIX_B)

    decree_part, rule_part = "", ""
    if rest:
        if rest.startswith(_APPENDIX_A):
            decree_part, after_decree = _split_at(rest, _APPENDIX_B)
            if after_decree:
                rule_part = after_decree
        elif rest.startswith(_APPENDIX_B):
            rule_part = rest

    # 응답 스키마 블록은 모든 파트에 첨부
    schema_block = ""
    schema_idx = text.find(_SCHEMA_MARKER)
    if schema_idx != -1:
        schema_block = "\n\n---\n\n" + text[schema_idx:]
    else:
        schema_block = "\n\n---\n\n" + expected_schema_excerpt()

    # main part에서 응답 스키마 제거 (중복 방지)
    main_part = main_part.replace(schema_block.strip(), "").rstrip()

    # 부록에서 응답 스키마 제거
    if decree_part:
        decree_part = re.sub(rf"\n*---\n*{re.escape(_SCHEMA_MARKER)}.*",
                              "", decree_part, flags=re.DOTALL).rstrip()
    if rule_part:
        rule_part = re.sub(rf"\n*---\n*{re.escape(_SCHEMA_MARKER)}.*",
                            "", rule_part, flags=re.DOTALL).rstrip()

    output_dir.mkdir(parents=True, exist_ok=True)
    parts: list[tuple[str, str]] = []
    total = 1 + (1 if decree_part else 0) + (1 if rule_part else 0)

    # Part 1: 본법
    h1 = _build_part_header(name, "본법 + 후보 finding", total, 1, is_main=True)
    parts.append((f"{name}__part1_본법.md",
                   h1 + main_part + schema_block))

    # Part 2: 시행령 부록 (있으면)
    if decree_part:
        h2 = _build_part_header(name, "시행령 전문", total, 2)
        parts.append((f"{name}__part2_시행령.md",
                       h2 + decree_part + schema_block))
    # Part 3: 시행규칙 부록
    if rule_part:
        idx = len(parts) + 1
        h3 = _build_part_header(name, "시행규칙 전문", total, idx)
        parts.append((f"{name}__part{idx}_시행규칙.md",
                       h3 + rule_part + schema_block))

    written: list[Path] = []
    for fname, content in parts:
        p = output_dir / fname
        p.write_text(content, encoding="utf-8")
        written.append(p)
    return written


def split_chapter_mode(md_path: Path, output_dir: Path, chunks: int = 3) -> list[Path]:
    """조문 단위 섹션을 N등분."""
    text = md_path.read_text(encoding="utf-8")
    name = md_path.stem

    # 본문 헤더 + 분석요약 (Part1 메타에 포함될 부분)
    art_section = re.search(r"^## 조문별 분석\b", text, re.MULTILINE)
    if not art_section:
        return split_appendix_mode(md_path, output_dir)
    preamble = text[:art_section.start()]

    # 조문 헤더 위치
    article_starts = [m.start() for m in re.finditer(r"^### 제\d+조", text[art_section.start():], re.MULTILINE)]
    article_starts = [s + art_section.start() for s in article_starts]
    if len(article_starts) < chunks:
        return split_appendix_mode(md_path, output_dir)

    # 응답 스키마
    schema_idx = text.find(_SCHEMA_MARKER)
    schema_block = "\n\n---\n\n" + (text[schema_idx:] if schema_idx != -1 else expected_schema_excerpt())

    # N등분
    per_chunk = len(article_starts) // chunks
    breakpoints = [article_starts[i * per_chunk] for i in range(chunks)] + [
        text.find(_APPENDIX_A) if _APPENDIX_A in text else (schema_idx if schema_idx != -1 else len(text))
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i in range(chunks):
        start, end = breakpoints[i], breakpoints[i + 1]
        h = _build_part_header(name, f"조문 {i+1}/{chunks} 묶음", chunks, i + 1,
                                is_main=(i == 0))
        body = (preamble if i == 0 else "## 조문별 분석 (이어서)\n\n") + text[start:end].rstrip()
        p = output_dir / f"{name}__chap{i+1}.md"
        p.write_text(h + body + schema_block, encoding="utf-8")
        written.append(p)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="judgment MD 분할")
    parser.add_argument("input", help="MD 파일 또는 디렉토리")
    parser.add_argument("--mode", choices=["appendix", "chapter", "auto"], default="auto")
    parser.add_argument("--chunks", type=int, default=3,
                        help="chapter 모드에서 분할 수")
    parser.add_argument("--max-kb", type=int, default=200,
                        help="auto 모드에서 이 크기 이상만 분할")
    parser.add_argument("--output-dir", default="outputs/chunks")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    inp = Path(args.input)
    targets: list[Path] = []
    if inp.is_dir():
        targets = sorted(inp.glob("*.md"))
    else:
        targets = [inp]

    written_total = 0
    skipped = 0
    for md in targets:
        kb = md.stat().st_size // 1024
        if args.mode == "auto" and kb < args.max_kb:
            skipped += 1
            continue
        mode = args.mode
        if mode == "auto":
            mode = "appendix"  # 기본은 부록 분리
        if mode == "appendix":
            written = split_appendix_mode(md, output_dir)
        else:
            written = split_chapter_mode(md, output_dir, chunks=args.chunks)
        written_total += len(written)
        if len(targets) == 1:
            for p in written:
                print(f"  {p.relative_to(Path.cwd()) if p.is_absolute() else p}  ({p.stat().st_size//1024}KB)",
                       file=sys.stderr)

    print(f"\n분할 완료: {written_total}개 파트 생성, {skipped}개 스킵 (크기 ≤ {args.max_kb}KB)",
           file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
