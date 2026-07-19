#!/usr/bin/env python3
"""Launch the TradingDatas V1 catalog/query service."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api_server  # noqa: E402


def main() -> None:
    api_server.main()


if __name__ == "__main__":
    main()
