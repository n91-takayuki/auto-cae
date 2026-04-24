"""Run the actual gmsh_runner pipeline on a STEP file end-to-end (mesh only)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import gmsh  # noqa: E402

from app.cad.step_loader import load_step  # noqa: E402
from app.mesh.gmsh_runner import mesh_and_write_inp  # noqa: E402
from app.schemas.jobs import FixBC, LoadBC, Material, MeshOptions  # noqa: E402

step = sys.argv[1] if len(sys.argv) > 1 else "plastic enclosue.STEP"
size_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
step_path = ROOT / step
out_dir = ROOT / "workdir" / "_test"
out_dir.mkdir(parents=True, exist_ok=True)

print(f"[STEP] {step_path}")
print(f"[size] {size_mm} mm")

g = load_step(str(step_path))
print(f"[OCP] {len(g.faces)} faces")

# Pick a face for fix and a face for load (just to satisfy the BC list)
bcs = [
    FixBC(faceIds=[g.faces[0].face_id], dofs={"x": True, "y": True, "z": True}),
    LoadBC(
        faceIds=[g.faces[1].face_id],
        magnitude=100.0,
        kind="force",
        direction="normal",
    ),
]
mat = Material()
opts = MeshOptions(sizeMm=size_mm)

gmsh.initialize()


def progress(v: float, msg: str) -> None:
    print(f"  [{v*100:5.1f}%] {msg}")


t = time.time()
try:
    res = mesh_and_write_inp(
        step_path=step_path,
        out_dir=out_dir,
        geometry=g,
        bcs=bcs,
        material=mat,
        options=opts,
        progress=progress,
    )
    print(f"\n[OK] strategy: {res.strategy_used}")
    print(f"     elements: {res.element_count}, nodes: {res.node_count}")
    print(f"     time: {time.time()-t:.1f}s")
    print(f"     inp: {res.inp_path}")
except Exception as e:
    print(f"\n[FAIL] {type(e).__name__}: {e}")
    print(f"     time: {time.time()-t:.1f}s")

gmsh.finalize()
