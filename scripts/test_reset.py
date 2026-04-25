"""Verify whether finalize+initialize between attempts clears gmsh state."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
step_path = str(ROOT / "PG7 Cable Gland.stp")

import gmsh

def attempt(label, *, algo3d, order):
    try:
        gmsh.finalize()
    except Exception:
        pass
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", 0.075)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", 1.5)
    gmsh.option.setNumber("Mesh.ElementOrder", order)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.Algorithm3D", algo3d)
    gmsh.model.add("t")
    gmsh.model.occ.importShapes(step_path)
    gmsh.model.occ.synchronize()
    t0 = time.time()
    try:
        gmsh.model.mesh.generate(3)
        et_types, et_tags, _ = gmsh.model.mesh.getElements(dim=3)
        n4 = sum(len(tt) for c, tt in zip(et_types, et_tags) if int(c) == 4)
        n10 = sum(len(tt) for c, tt in zip(et_types, et_tags) if int(c) == 11)
        print(f"[{label}] OK ({time.time()-t0:.1f}s) tet4={n4} tet10={n10}")
        return n4 > 0 or n10 > 0
    except Exception as e:
        print(f"[{label}] FAIL: {e}")
        return False


# Sequence: HXT (will fail), then Frontal (should succeed if reset works)
print("Test 1: HXT first, then Frontal")
attempt("HXT", algo3d=10, order=1)
attempt("Frontal", algo3d=4, order=1)

print("\nTest 2: Frontal first (control)")
attempt("Frontal solo", algo3d=4, order=1)
