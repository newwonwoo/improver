#!/usr/bin/env python3
"""FastAPI 서버 실행 진입점.

사용법:
    python scripts/serve.py --host 0.0.0.0 --port 8080
필요 패키지: fastapi, uvicorn, pydantic
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.api import create_app  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="improver HTTP 서버")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    try:
        import uvicorn  # noqa: WPS433
    except ImportError:
        print("uvicorn 미설치. `pip install uvicorn fastapi pydantic`", file=sys.stderr)
        return 1

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
