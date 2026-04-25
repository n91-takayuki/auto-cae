"""Force bad elements by disabling HighOrderOptimize and verify the flatten-repair
workflow drops their count to zero."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import gmsh  # noqa: E402

from app.mesh import gmsh_runner  # noqa: E402
from app.cad.step_loader import load_step  # noqa: E402

step = sys.argv[1] if len(sys.argv) > 1 else "plastic enclosue.STEP"
size_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
step_path = ROOT / step

g = load_step(str(step_path))

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("stress")
gmsh.model.occ.importShapes(str(step_path))
gmsh.model.occ.synchronize()

# Minimal setup: order 2 WITHOUT HighOrderOptimize or Netgen,
# to reproduce the original bad-Jacobian scenario.
gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_mm * 0.25)
gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_mm)
gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
gmsh.option.setNumber("Mesh.ElementOrder", 2)
gmsh.option.setNumber("Mesh.Algorithm", 6)
gmsh.option.setNumber("Mesh.Algorithm3D", 1)
gmsh.option.setNumber("Mesh.Optimize", 1)
gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)
gmsh.option.setNumber("Mesh.HighOrderOptimize", 0)

gmsh.model.mesh.generate(3)

ok, total, bad_before = gmsh_runner._check_quality(gmsh, max_bad_ratio=0.0)
print(f"[before] tet10 total={total}, bad (minSJ<=0)={bad_before}, quality OK={ok}")

n_rep, centroids = gmsh_runner._flatten_bad_midside_nodes(gmsh)
print(f"[repair] flattened {n_rep} elements")

ok, total2, bad_after = gmsh_runner._check_quality(gmsh, max_bad_ratio=0.0)
print(f"[after]  tet10 total={total2}, bad (minSJ<=0)={bad_after}, quality OK={ok}")

if centroids:
    print(f"[sample centroids] first 3:")
    for c in centroids[:3]:
        print(f"   ({c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f})")

gmsh.finalize()
