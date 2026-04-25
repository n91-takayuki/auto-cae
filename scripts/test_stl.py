"""Time STL-rebuild meshing on PG7."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import gmsh
import numpy as np

from app.cad.step_loader import load_step

step_path = ROOT / "PG7 Cable Gland.stp"
size_mm = float(sys.argv[1]) if len(sys.argv) > 1 else 1.5
algo3d = int(sys.argv[2]) if len(sys.argv) > 2 else 10

t0 = time.time()
g = load_step(str(step_path))
print(f"[OCP load] {time.time()-t0:.1f}s, {len(g.faces)} faces")

stl_path = ROOT / "workdir" / "_pg7.stl"
t0 = time.time()
with open(stl_path, "w") as f:
    f.write("solid m\n")
    for face in g.faces:
        pts = np.asarray(face.positions).reshape(-1, 3)
        idx = np.asarray(face.indices, dtype=np.int64).reshape(-1, 3)
        for tri in idx:
            a, b, c = pts[tri[0]], pts[tri[1]], pts[tri[2]]
            n = np.cross(b - a, c - a)
            ln = float(np.linalg.norm(n))
            if ln < 1e-18:
                continue
            n = n / ln
            f.write(f"facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
            f.write("outer loop\n")
            f.write(f"vertex {a[0]:.6e} {a[1]:.6e} {a[2]:.6e}\n")
            f.write(f"vertex {b[0]:.6e} {b[1]:.6e} {b[2]:.6e}\n")
            f.write(f"vertex {c[0]:.6e} {c[1]:.6e} {c[2]:.6e}\n")
            f.write("endloop\n")
            f.write("endfacet\n")
    f.write("endsolid m\n")
print(f"[STL write] {time.time()-t0:.1f}s, size={stl_path.stat().st_size//1024}KB")

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_mm * 0.25)
gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_mm)
gmsh.option.setNumber("Mesh.ElementOrder", 1)
gmsh.option.setNumber("Mesh.Algorithm", 6)
gmsh.option.setNumber("Mesh.Algorithm3D", algo3d)

t0 = time.time()
gmsh.merge(str(stl_path))
print(f"[merge] {time.time()-t0:.1f}s")

t0 = time.time()
angle = 40.0 * np.pi / 180.0
gmsh.model.mesh.classifySurfaces(angle, True, True, np.pi)
gmsh.model.mesh.createGeometry()
print(f"[classify+createGeometry] {time.time()-t0:.1f}s")

surfaces = [s for _d, s in gmsh.model.getEntities(2)]
print(f"  {len(surfaces)} reconstructed surfaces")
loop = gmsh.model.geo.addSurfaceLoop(surfaces)
gmsh.model.geo.addVolume([loop])
gmsh.model.geo.synchronize()

t0 = time.time()
try:
    gmsh.model.mesh.generate(3)
    et_types, et_tags, _ = gmsh.model.mesh.getElements(dim=3)
    n4 = sum(len(tt) for c, tt in zip(et_types, et_tags) if int(c) == 4)
    n10 = sum(len(tt) for c, tt in zip(et_types, et_tags) if int(c) == 11)
    print(f"[mesh3D] {time.time()-t0:.1f}s, tet4={n4}, tet10={n10}")
except Exception as e:
    print(f"[mesh3D] FAILED ({time.time()-t0:.1f}s): {e}")

gmsh.finalize()
