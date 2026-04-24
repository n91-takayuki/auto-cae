"""Diagnose meshing on a STEP file: report geometry stats + try each strategy."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import gmsh  # noqa: E402
import numpy as np  # noqa: E402

from app.cad.step_loader import load_step  # noqa: E402

step_path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "plastic enclosue.STEP")
size_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

print(f"[step] {step_path}")
print(f"[size] {size_mm} mm")
print()

# 1. OCP geometry stats
t0 = time.time()
g = load_step(step_path)
print(f"[OCP] faces={len(g.faces)}, total_tri={sum(f.tri_count for f in g.faces)}")
print(f"[OCP] bbox: {g.bbox_min} -> {g.bbox_max}")
sx = g.bbox_max[0] - g.bbox_min[0]
sy = g.bbox_max[1] - g.bbox_min[1]
sz = g.bbox_max[2] - g.bbox_min[2]
diag = (sx**2 + sy**2 + sz**2) ** 0.5
print(f"[OCP] bbox span: {sx:.2f} x {sy:.2f} x {sz:.2f}, diag={diag:.2f}")
print(f"[OCP] load time: {time.time()-t0:.2f}s")

face_areas = []
for f in g.faces:
    pts = np.asarray(f.positions, dtype=np.float64).reshape(-1, 3)
    idx = np.asarray(f.indices, dtype=np.int64).reshape(-1, 3)
    a = 0.0
    for tri in idx:
        v1 = pts[tri[1]] - pts[tri[0]]
        v2 = pts[tri[2]] - pts[tri[0]]
        a += 0.5 * float(np.linalg.norm(np.cross(v1, v2)))
    face_areas.append(a)
face_areas.sort()
print(f"[OCP] face areas (mm^2): min={face_areas[0]:.4g}, median={face_areas[len(face_areas)//2]:.4g}, max={face_areas[-1]:.4g}")
print(f"[OCP] target element area: {(size_mm/2)**2:.4g} mm^2")
small = sum(1 for a in face_areas if a < (size_mm/2)**2)
tiny = sum(1 for a in face_areas if a < (size_mm/4)**2)
print(f"[OCP] small faces (< (size/2)^2): {small} / {len(face_areas)}")
print(f"[OCP] tiny  faces (< (size/4)^2): {tiny}")
print()

# 2. Try gmsh import with various options
gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 1)


def try_strategy(label, *, heal=False, heal_tol=None, defeature=False, algo3d=10, order=1):
    print(f"\n=== [{label}] heal={heal} heal_tol={heal_tol} defeature={defeature} algo3d={algo3d} order={order} ===")
    try:
        gmsh.clear()
    except Exception:
        pass
    gmsh.option.setNumber("Geometry.OCCAutoFix", 1 if heal else 0)
    gmsh.option.setNumber("Geometry.OCCFixDegenerated", 1 if heal else 0)
    gmsh.option.setNumber("Geometry.OCCFixSmallEdges", 1 if heal else 0)
    gmsh.option.setNumber("Geometry.OCCFixSmallFaces", 1 if heal else 0)
    gmsh.option.setNumber("Geometry.OCCSewFaces", 1 if heal else 0)
    gmsh.option.setNumber("Geometry.OCCMakeSolids", 1 if heal else 0)
    gmsh.option.setNumber("Geometry.Tolerance", max(diag * 1e-5, 1e-6))

    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_mm * 0.25)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_mm)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.ElementOrder", order)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.Algorithm3D", algo3d)
    gmsh.option.setNumber("Mesh.Optimize", 1)

    t = time.time()
    gmsh.model.add("diag")
    try:
        gmsh.model.occ.importShapes(step_path)
    except Exception as e:
        print(f"  importShapes failed: {e}")
        return False

    if heal:
        try:
            gmsh.model.occ.healShapes()
        except Exception as e:
            print(f"  healShapes(default) failed: {e}")
        if heal_tol:
            try:
                gmsh.model.occ.healShapes(
                    dimTags=[],
                    tolerance=float(heal_tol),
                    fixDegenerated=True,
                    fixSmallEdges=True,
                    fixSmallFaces=True,
                    sewFaces=True,
                    makeSolids=True,
                )
            except Exception as e:
                print(f"  healShapes(tol={heal_tol}) failed: {e}")
        try:
            gmsh.model.occ.removeAllDuplicates()
        except Exception:
            pass
    gmsh.model.occ.synchronize()

    nfaces = len(gmsh.model.getEntities(2))
    nvols = len(gmsh.model.getEntities(3))
    print(f"  after import: {nfaces} faces, {nvols} volumes ({time.time()-t:.2f}s)")

    if defeature:
        thr = (size_mm * 0.5) ** 2
        smalls = []
        for _, t2 in gmsh.model.getEntities(2):
            try:
                if gmsh.model.occ.getMass(2, t2) < thr:
                    smalls.append(int(t2))
            except Exception:
                pass
        if smalls:
            try:
                gmsh.model.occ.defeature([int(v) for _, v in gmsh.model.getEntities(3)], smalls)
                gmsh.model.occ.synchronize()
                print(f"  defeatured {len(smalls)} small faces -> {len(gmsh.model.getEntities(2))} faces")
            except Exception as e:
                print(f"  defeature failed: {e}")

    try:
        t1 = time.time()
        gmsh.model.mesh.generate(3)
        dt = time.time() - t1
        et_types, _, _ = gmsh.model.mesh.getElements(dim=3)
        ntet4 = ntet10 = 0
        for code in et_types:
            if int(code) == 4: ntet4 += 1
            elif int(code) == 11: ntet10 += 1
        nodes, _, _ = gmsh.model.mesh.getNodes()
        print(f"  [OK] MESHED in {dt:.2f}s: nodes={len(nodes)}, tet4_blocks={ntet4}, tet10_blocks={ntet10}")
        if order == 1 and ntet4 > 0:
            t2 = time.time()
            gmsh.model.mesh.setOrder(2)
            print(f"  setOrder(2) in {time.time()-t2:.2f}s")
        return True
    except Exception as e:
        print(f"  [NG] generate(3) failed: {e}")
        return False


# Try each major strategy
strategies = [
    dict(label="default", heal=False, algo3d=1, order=2),
    dict(label="HXT-2", heal=False, algo3d=10, order=2),
    dict(label="heal-default + HXT", heal=True, algo3d=10, order=2),
    dict(label="heal-default + HXT + lin", heal=True, algo3d=10, order=1),
    dict(label="heal target/4", heal=True, heal_tol=size_mm * 0.25, algo3d=10, order=1),
    dict(label="heal target/2", heal=True, heal_tol=size_mm * 0.5, algo3d=10, order=1),
    dict(label="heal target", heal=True, heal_tol=size_mm * 1.0, algo3d=10, order=1),
    dict(label="defeature small + heal/2", heal=True, heal_tol=size_mm * 0.5, defeature=True, algo3d=10, order=1),
]

t_total = time.time()
for s in strategies:
    ok = try_strategy(**s)
    if ok:
        print(f"\n*** SUCCESS with [{s['label']}] (total elapsed: {time.time()-t_total:.1f}s) ***")
        break
else:
    print(f"\n!!! ALL FAILED (total elapsed: {time.time()-t_total:.1f}s)")

gmsh.finalize()
