from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKDIR = Path(os.environ.get("AUTO_CAE_WORKDIR", ROOT / "workdir"))
CCX_PATH = os.environ.get("CCX_PATH", "ccx")

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

WORKDIR.mkdir(parents=True, exist_ok=True)
