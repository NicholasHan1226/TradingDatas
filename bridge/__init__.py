"""Bridge module search path compatibility for local and production layouts."""

from __future__ import annotations

import os
from pathlib import Path

_SHAREDSIGNALS_ROOT = Path(__file__).resolve().parents[1]
_FINANCE_ROOT = _SHAREDSIGNALS_ROOT.parent
_MARKETGRAPH_ROOT = Path(os.environ.get("MARKETGRAPH_ROOT") or _FINANCE_ROOT / "MarketGraph")

for _path in (
    _MARKETGRAPH_ROOT / "tools",
    _MARKETGRAPH_ROOT / "08-Market-Interfaces" / "tools",
    Path("/opt/investment/MarketGraph/tools"),
    Path("/opt/investment/MarketGraph/08-Market-Interfaces/tools"),
):
    if _path.exists():
        __path__.append(str(_path))
