"""More attempts for PG7 — try curvature-based size, defeature, healing."""
from __future__ import annotations

import sys
import time
import subprocess

ROOT = sys.path[0] if False else None
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import gmsh  # noqa: E402

step_path = str(ROOT / "PG7 Cable Gland.stp")


def setup_common(size_mm):
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_mm * 0.05)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_mm)
    gmsh.option.setNumber("Mesh.ElementOrder", 1)
    gmsh.option.setNumber("Mesh.Algorithm", 6)


def attempt(label, *, size_mm=1.5, algo3d=10,
            curvature_n=0, heal=False, heal_tol=0,
            defeature_factor=0):
    print(f"\n=== {label} ===")
    try:
        gmsh.clear()
    except Exception:
        pass
    setup_common(size_mm)
    gmsh.option.setNumber("Mesh.Algorithm3D", algo3d)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", curvature_n)

    if heal:
        gmsh.option.setNumber("Geometry.OCCAutoFix", 1)
        gmsh.option.setNumber("Geometry.OCCFixDegenerated", 1)
        gmsh.option.setNumber("Geometry.OCCFixSmallEdges", 1)
        gmsh.option.setNumber("Geometry.OCCFixSmallFaces", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
        if heal_tol > 0:
            gmsh.option.setNumber("Geometry.Tolerance", heal_tol)
    else:
        gmsh.option.setNumber("Geometry.OCCAutoFix", 0)

    gmsh.model.add("pg7")
    t = time.time()
    try:
        gmsh.model.occ.importShapes(step_path)
    except Exception as e:
        print(f"  import FAILED: {e}")
        return False

    if heal and heal_tol > 0:
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
            print(f"  healShapes(tol={heal_tol}) OK")
        except Exception as e:
            print(f"  healShapes failed: {e}")

    gmsh.model.occ.synchronize()
    nf = len(gmsh.model.getEntities(2))
    print(f"  imported in {time.time()-t:.1f}s, {nf} faces")

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
                nf2 = len(gmsh.model.getEntities(2))
                print(f"  defeatured {len(smalls)} small faces -> {nf2} faces")
            except Exception as e:
                print(f"  defeature failed: {e}")

    try:
        t1 = time.time()
        gmsh.model.mesh.generate(3)
        et_types, et_tags, _ = gmsh.model.mesh.getElements(dim=3)
        ne = sum(len(t) for c, t in zip(et_types, et_tags) if int(c) in (4, 11))
        print(f"  3D MESH OK ({time.time()-t1:.1f}s) elements={ne}")
        return ne > 0
    except Exception as e:
        print(f"  3D mesh FAILED: {e}")
        return False


gmsh.initialize()

attempts = [
    dict(label="curvature=12 + HXT", curvature_n=12),
    dict(label="curvature=20 + HXT", curvature_n=20),
    dict(label="curvature=12 + Delaunay", algo3d=1, curvature_n=12),
    dict(label="defeature 0.3", defeature_factor=0.3),
    dict(label="defeature 0.5", defeature_factor=0.5),
    dict(label="defeature 1.0", defeature_factor=1.0),
    dict(label="heal+defeature 0.5", heal=True, heal_tol=0.3, defeature_factor=0.5),
    dict(label="heal-loose only", heal=True, heal_tol=1.0),
    dict(label="heal+curvature=12", heal=True, heal_tol=0.5, curvature_n=12),
    dict(label="size=2.5mm + curvature", size_mm=2.5, curvature_n=12),
    dict(label="size=2.5mm + defeature 0.5", size_mm=2.5, defeature_factor=0.5),
    dict(label="size=2.5mm + heal", size_mm=2.5, heal=True, heal_tol=0.5),
]

for cfg in attempts:
    if attempt(**cfg):
        print(f"\n*** SUCCESS: {cfg['label']} ***")
        break
else:
    print("\n!!! ALL FAILED !!!")
gmsh.finalize()
