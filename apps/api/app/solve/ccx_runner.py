"""CalculiX (ccx) subprocess runner with progress parsing."""
from __future__ import annotations

import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import CCX_PATH

ProgressFn = Callable[[float, str], None]

# Lines in ccx stdout like:
#   " STEP    1"
#   " INCREMENT    1"
#   " Job finished"
_STEP_RE = re.compile(r"^\s*STEP\s+(\d+)", re.IGNORECASE)
_INC_RE = re.compile(r"^\s*INCREMENT\s+(\d+)", re.IGNORECASE)


@dataclass
class CcxResult:
    frd_path: Path
    log_path: Path
    returncode: int


class CcxRunError(RuntimeError):
    pass


def run_ccx(
    inp_path: Path,
    progress: ProgressFn | None = None,
    timeout_s: float = 300.0,
) -> CcxResult:
    """Run ccx on ``inp_path`` (without the .inp extension CalculiX expects).

    ccx expects: ccx <jobname>  where <jobname>.inp must exist in cwd.
    """
    jobname = inp_path.stem
    cwd = inp_path.parent

    log_path = cwd / f"{jobname}.log"

    def p(v: float, msg: str) -> None:
        if progress:
            progress(v, msg)

    p(0.05, "ccx: launching")

    proc = subprocess.Popen(
        [CCX_PATH, jobname],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Stream output, record for log, and parse progress heuristics.
    log_lines: list[str] = []
    last_step = 0
    last_inc = 0
    killed = {"flag": False}

    def _watchdog() -> None:
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            killed["flag"] = True
            proc.terminate()

    wd = threading.Thread(target=_watchdog, daemon=True)
    wd.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            log_lines.append(line)
            ls = line.rstrip()
            if not ls:
                continue
            if m := _STEP_RE.match(ls):
                last_step = int(m.group(1))
                p(min(0.5 + 0.05 * last_step, 0.85), f"ccx: step {last_step}")
            elif m := _INC_RE.match(ls):
                last_inc = int(m.group(1))
                p(min(0.55 + 0.05 * last_inc, 0.9), f"ccx: increment {last_inc}")
            elif "Job finished" in ls:
                p(0.92, "ccx: finalizing")
    finally:
        rc = proc.wait()
        wd.join(timeout=0.1)

    log_path.write_text("".join(log_lines), encoding="utf-8", errors="replace")

    if killed["flag"]:
        raise CcxRunError(f"ccx timed out after {timeout_s:.0f}s (see {log_path})")

    frd_path = cwd / f"{jobname}.frd"
    if rc != 0 or not frd_path.exists():
        tail = "".join(log_lines[-30:])
        raise CcxRunError(f"ccx failed (rc={rc}). Tail:\n{tail}")

    return CcxResult(frd_path=frd_path, log_path=log_path, returncode=rc)
