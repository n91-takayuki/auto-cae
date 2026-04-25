"""STL with vertex deduplication + various recovery options."""
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

g = load_step(str(step_path))
print(f"[OCP] {len(g.faces)} faces")

# Build STL with vertex deduplication
eps = max(size_mm * 0.001, 1e-4)
print(f"[merge tol] {eps}")
all_pts = []
key_to_idx = {}


def get_idx(p):
    k = (round(p[0] / eps), round(p[1] / eps), round(p[2] / eps))
    if k not in key_to_idx:
        key_to_idx[k] = len(all_pts)
        all_pts.append(p)
    return key_to_idx[k]


tris = []
for face in g.faces:
    pts = np.asarray(face.positions).reshape(-1, 3)
    idx = np.asarray(face.indices, dtype=np.int64).reshape(-1, 3)
    for tri in idx:
        ia = get_idx(pts[tri[0]])
        ib = get_idx(pts[tri[1]])
        ic = get_idx(pts[tri[2]])
        if ia == ib or ib == ic or ia == ic:
            continue
        tris.append((ia, ib, ic))

print(f"[dedup] verts={len(all_pts)}, tris={len(tris)}")

stl_path = ROOT / "workdir" / "_pg7m.stl"
with open(stl_path, "w") as f:
    f.write("solid m\n")
    for ia, ib, ic in tris:
        a, b, c = all_pts[ia], all_pts[ib], all_pts[ic]
        n = np.cross(b - a, c - a)
        ln = float(np.linalg.norm(n))
        if ln < 1e-18:
            continue
        n = n / ln
        f.write(f"facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
        f.write("outer loop\n")
        for v in (a, b, c):
            f.write(f"vertex {v[0]:.6e} {v[1]:.6e} {v[2]:.6e}\n")
        f.write("endloop\nendfacet\n")
    f.write("endsolid m\n")


def attempt(label, *, algo3d, classify_angle_deg=40.0, use_create_geometry=True):
    print(f"\n=== {label} ===")
    try:
        gmsh.finalize()
    except Exception:
        pass
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_mm * 0.25)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_mm)
    gmsh.option.setNumber("Mesh.ElementOrder", 1)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.Algorithm3D", algo3d)
    gmsh.option.setNumber("Mesh.AngleToleranceFacetOverlap", 0.05)

    t = time.time()
    gmsh.merge(str(stl_path))
    try:
        gmsh.model.mesh.removeDuplicateNodes()
    except Exception:
        pass
    print(f"  merge+dedup: {time.time()-t:.1f}s")

    angle = classify_angle_deg * np.pi / 180.0
    try:
        gmsh.model.mesh.classifySurfaces(angle, True, True, np.pi)
    except Exception as e:
        print(f"  classifySurfaces failed: {e}")
        return False

    if use_create_geometry:
        try:
            gmsh.model.mesh.createGeometry()
        except Exception as e:
            print(f"  createGeometry failed: {e}")
            return False

    surfaces = [s for _d, s in gmsh.model.getEntities(2)]
    print(f"  {len(surfaces)} reconstructed surfaces")
    if not surfaces:
        return False

    try:
        loop = gmsh.model.geo.addSurfaceLoop(surfaces)
        gmsh.model.geo.addVolume([loop])
        gmsh.model.geo.synchronize()
    except Exception as e:
        print(f"  addVolume failed: {e}")
        return False

    t = time.time()
    try:
        gmsh.model.mesh.generate(3)
    except Exception as e:
        print(f"  3D mesh failed ({time.time()-t:.1f}s): {e}")
        return False

    et_types, et_tags, _ = gmsh.model.mesh.getElements(dim=3)
    n = sum(len(tt) for c, tt in zip(et_types, et_tags) if int(c) in (4, 11))
    print(f"  3D mesh OK ({time.time()-t:.1f}s) elements={n}")
    return n > 0


for cfg in [
    dict(label="HXT angle=40", algo3d=10, classify_angle_deg=40),
    dict(label="HXT angle=20", algo3d=10, classify_angle_deg=20),
    dict(label="HXT angle=60", algo3d=10, classify_angle_deg=60),
    dict(label="Delaunay angle=40", algo3d=1, classify_angle_deg=40),
    dict(label="Frontal angle=40", algo3d=4, classify_angle_deg=40),
]:
    if attempt(**cfg):
        print(f"\n*** SUCCESS: {cfg['label']} ***")
        break
else:
    print("\n!!! ALL FAILED")

try:
    gmsh.finalize()
except Exception:
    pass
