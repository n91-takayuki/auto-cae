"""Check that all Auto-CAE runtime dependencies are available."""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys


def check_module(name: str, version_attr: str = "__version__") -> tuple[bool, str]:
    try:
        mod = importlib.import_module(name)
        v = getattr(mod, version_attr, "?")
        return True, v
    except Exception as e:
        return False, str(e)


def check_exec(cmd: str) -> tuple[bool, str]:
    path = shutil.which(cmd)
    if not path:
        return False, "not found in PATH"
    try:
        out = subprocess.run([path], capture_output=True, text=True, timeout=5).stdout.strip()
        return True, (out.splitlines() or [path])[0][:80]
    except Exception:
        return True, path


def main() -> int:
    print("== Auto-CAE doctor ==")
    print(f"python : {sys.version.split()[0]}  ({sys.executable})")

    rows = [
        ("fastapi", check_module("fastapi")),
        ("uvicorn", check_module("uvicorn")),
        ("numpy", check_module("numpy")),
        ("ocp", check_module("OCP.STEPControl", version_attr="__doc__")),
        ("gmsh", check_module("gmsh")),
    ]

    ccx_path = os.environ.get("CCX_PATH", "ccx")
    rows.append(("ccx", check_exec(ccx_path)))

    ok = True
    for name, (found, info) in rows:
        mark = "[ok] " if found else "[NG] "
        if not found:
            ok = False
        print(f"{mark}{name:12s} {info}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
