"""Single-shot mesh test for one config (fresh process)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import gmsh  # noqa: E402

step = sys.argv[1]
size_mm = float(sys.argv[2])
algo3d = int(sys.argv[3])
order = int(sys.argv[4])
curvature_n = int(sys.argv[5]) if len(sys.argv) > 5 else 0
defeature_factor = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0

step_path = str(ROOT / step)

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_mm * 0.05)
gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_mm)
gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", curvature_n)
gmsh.option.setNumber("Mesh.ElementOrder", order)
gmsh.option.setNumber("Mesh.Algorithm", 6)
gmsh.option.setNumber("Mesh.Algorithm3D", algo3d)
gmsh.option.setNumber("Mesh.Optimize", 1)
if order == 2:
    gmsh.option.setNumber("Mesh.HighOrderOptimize", 2)

gmsh.model.add("t")
t = time.time()
gmsh.model.occ.importShapes(step_path)
gmsh.model.occ.synchronize()
nf = len(gmsh.model.getEntities(2))
print(f"[import] {nf} faces in {time.time()-t:.1f}s")

if defeature_factor > 0:
    thr = (size_mm * defeature_factor) ** 2
    smalls = []
    for _, t2 in gmsh.model.getEntities(2):
        try:
            if gmsh.model.occ.getMass(2, t2) < thr:
                smalls.append(int(t2))
        except Exception:
            pass
    vols = [int(v) for _, v in gmsh.model.getEntities(3)]
    if smalls and vols:
        try:
            gmsh.model.occ.defeature(vols, smalls)
            gmsh.model.occ.synchronize()
            print(f"[defeature] {len(smalls)} faces removed -> {len(gmsh.model.getEntities(2))} faces")
        except Exception as e:
            print(f"[defeature] FAILED: {e}")
            sys.exit(1)

t1 = time.time()
try:
    gmsh.model.mesh.generate(3)
except Exception as e:
    print(f"[mesh] FAILED: {e}")
    sys.exit(2)

et_types, et_tags, _ = gmsh.model.mesh.getElements(dim=3)
n4 = sum(len(tt) for c, tt in zip(et_types, et_tags) if int(c) == 4)
n10 = sum(len(tt) for c, tt in zip(et_types, et_tags) if int(c) == 11)
print(f"[mesh] OK in {time.time()-t1:.1f}s, tet4={n4}, tet10={n10}")
gmsh.finalize()
