"""Diagnose PG7 Cable Gland failure: focus on what works at 2D and 3D stages."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import gmsh  # noqa: E402

step = sys.argv[1] if len(sys.argv) > 1 else "PG7 Cable Gland.stp"
size_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5
step_path = str(ROOT / step)


def attempt(label, *, algo3d, order=1, cleanup_2d=False, recover_lost=False):
    print(f"\n=== {label} ===")
    try:
        gmsh.clear()
    except Exception:
        pass
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_mm * 0.25)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_mm)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.ElementOrder", order)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.Algorithm3D", algo3d)
    gmsh.option.setNumber("Mesh.AngleToleranceFacetOverlap", 0.05)
    if recover_lost:
        gmsh.option.setNumber("Mesh.AlgorithmSwitchOnFailure", 1)

    gmsh.model.add("d")
    gmsh.model.occ.importShapes(step_path)
    gmsh.model.occ.synchronize()

    t = time.time()
    try:
        gmsh.model.mesh.generate(2)
        print(f"  2D mesh: OK ({time.time()-t:.1f}s)")
    except Exception as e:
        print(f"  2D mesh FAILED: {e}")
        return False

    if cleanup_2d in ("nodes", "nodes_reclass"):
        try:
            gmsh.model.mesh.removeDuplicateNodes()
            tags2d, _, _ = gmsh.model.mesh.getNodes()
            print(f"  removeDuplicateNodes -> {len(tags2d)} nodes")
        except Exception as e:
            print(f"  removeDuplicateNodes failed: {e}")
    if cleanup_2d in ("reclass", "nodes_reclass"):
        try:
            gmsh.model.mesh.reclassifyNodes()
            print("  reclassifyNodes: OK")
        except Exception as e:
            print(f"  reclassifyNodes failed: {e}")

    try:
        t1 = time.time()
        gmsh.model.mesh.generate(3)
        print(f"  3D mesh: OK ({time.time()-t1:.1f}s)")
        et_types, et_tags, _ = gmsh.model.mesh.getElements(dim=3)
        n4 = sum(len(tags) for c, tags in zip(et_types, et_tags) if int(c) == 4)
        n10 = sum(len(tags) for c, tags in zip(et_types, et_tags) if int(c) == 11)
        print(f"  elements: tet4={n4}, tet10={n10}")
        return True
    except Exception as e:
        print(f"  3D mesh FAILED: {e}")
        return False


gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)

attempts = [
    dict(label="HXT + removeDupNodes only",     algo3d=10, order=1, cleanup_2d="nodes"),
    dict(label="Delaunay + removeDupNodes",     algo3d=1,  order=1, cleanup_2d="nodes"),
    dict(label="Frontal + removeDupNodes",      algo3d=4,  order=1, cleanup_2d="nodes"),
    dict(label="HXT + reclassify only",         algo3d=10, order=1, cleanup_2d="reclass"),
    dict(label="Delaunay + reclassify",         algo3d=1,  order=1, cleanup_2d="reclass"),
    dict(label="Delaunay + dup+reclass",        algo3d=1,  order=1, cleanup_2d="nodes_reclass"),
]

for cfg in attempts:
    ok = attempt(**cfg)
    if ok:
        print(f"\n*** SUCCESS: {cfg['label']} ***")
        break
else:
    print("\n!!! ALL FAILED !!!")

gmsh.finalize()
