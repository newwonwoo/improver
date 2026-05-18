#!/usr/bin/env python3
"""config 파일 무결성 검증.

사용법:
    python scripts/validate_config.py
    python scripts/validate_config.py --strict   # 경고도 실패로 취급
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config_validator import validate_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="config 무결성 검증")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--strict", action="store_true",
                        help="경고도 실패(non-zero exit)로 취급")
    args = parser.parse_args(argv)

    reports = validate_all(Path(args.config_dir))
    has_error = False
    for r in reports:
        print(f"== {r.file} ==", file=sys.stdout)
        if r.errors:
            has_error = True
            for e in r.errors:
                print(f"  [ERROR] {e}", file=sys.stdout)
        if r.warnings:
            for w in r.warnings[:10]:
                print(f"  [warn] {w}", file=sys.stdout)
            if len(r.warnings) > 10:
                print(f"  … 외 경고 {len(r.warnings) - 10}건", file=sys.stdout)
        if r.ok and not r.warnings:
            print("  ✓ OK", file=sys.stdout)
        print(file=sys.stdout)

    if has_error or (args.strict and any(r.warnings for r in reports)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
