"""Gmsh meshing + CalculiX .inp writing with BC injection.

This module is single-threaded (gmsh is a process-global singleton).
Callers must serialize via the module-level lock in ``mesh_and_write_inp``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable

import numpy as np

from ..cad.step_loader import GeometryPayload
from ..schemas.jobs import BC, FixBC, LoadBC, Material, MeshOptions

ProgressFn = Callable[[float, str], None]

_GMSH_LOCK = Lock()


@dataclass
class MeshResult:
    inp_path: Path
    node_count: int
    element_count: int
    node_tags: np.ndarray       # int64, shape (N,)
    node_coords: np.ndarray     # float64, shape (N, 3)   in mm
    tet_conn: np.ndarray        # int64, shape (E, 10)
    surface_tris: np.ndarray    # int64, shape (T, 3)
    strategy_used: str = ""


# Meshing strategies tried in order. Each has progressively more aggressive
# healing / more robust algorithms. We do not change the user-requested mesh
# size in any of them (size is the user's responsibility).
@dataclass(frozen=True)
class _Strategy:
    name: str
    source: str         # "step" -> import OCC STEP   /  "stl" -> rebuild from OCP tessellation
    heal: bool          # apply OCC heal + remove duplicates after import (step only)
    algo2d: int         # Mesh.Algorithm   (1=MeshAdapt, 2=Auto, 5=Delaunay, 6=Frontal-Delaunay, 8=FrontalQuad)
    algo3d: int         # Mesh.Algorithm3D (1=Delaunay, 4=Frontal, 7=MMG3D, 9=R-tree, 10=HXT)
    order_at_gen: int   # 2: gen tet10 directly. 1: gen tet4, then setOrder(2)
    heal_tol_scale: float = 1e-5   # OCC tolerance = diag * heal_tol_scale (only when heal=True)


_STRATEGIES: list[_Strategy] = [
    _Strategy("STEP default",            "step", False, 6, 1, 2),
    _Strategy("STEP HXT",                "step", False, 6, 10, 2),
    _Strategy("STEP heal + HXT",         "step", True,  6, 10, 2,  heal_tol_scale=1e-5),
    _Strategy("STEP heal + HXT + lin",   "step", True,  6, 10, 1,  heal_tol_scale=1e-5),
    _Strategy("STEP heal-loose + HXT",   "step", True,  6, 10, 1,  heal_tol_scale=1e-3),
    _Strategy("STEP heal + Delaunay",    "step", True,  5, 1,  1,  heal_tol_scale=1e-4),
    _Strategy("STEP heal + Frontal",     "step", True,  1, 4,  1,  heal_tol_scale=1e-4),
    # Last resort: rebuild geometry from OCP per-face tessellation as a discrete STL,
    # then let gmsh classify surfaces and tet-mesh from scratch. Bypasses STEP topology.
    _Strategy("STL discrete + HXT + lin","stl",  False, 6, 10, 1),
    _Strategy("STL discrete + Delaunay", "stl",  False, 5, 1,  1),
]


def mesh_and_write_inp(
    step_path: Path,
    out_dir: Path,
    geometry: GeometryPayload,
    bcs: list[BC],
    material: Material,
    options: MeshOptions,
    progress: ProgressFn | None = None,
) -> MeshResult:
    """Load STEP via gmsh, mesh to tet10, and write a CalculiX .inp with BCs.

    Tries multiple strategies in order; the first that produces a valid tet10
    mesh wins. Mesh size is taken verbatim from ``options.sizeFactor`` and is
    NOT altered between strategies.
    """
    import gmsh

    def p(v: float, msg: str) -> None:
        if progress:
            progress(v, msg)

    # Characteristic size: explicit sizeMm wins, otherwise bbox / 20 * sizeFactor.
    xmin, ymin, zmin = geometry.bbox_min
    xmax, ymax, zmax = geometry.bbox_max
    diag = float(((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5)
    if options.sizeMm is not None and options.sizeMm > 0:
        target = float(options.sizeMm)
    else:
        target = max(diag / 20.0 * options.sizeFactor, 1e-3)

    # Pre-build STL once if any STL strategy might be used
    stl_path = out_dir / "_recon.stl"
    stl_built = False

    with _GMSH_LOCK:
        last_err: Exception | None = None
        for i, strat in enumerate(_STRATEGIES):
            stage_lo = 0.05 + 0.55 * (i / len(_STRATEGIES))
            stage_hi = 0.05 + 0.55 * ((i + 1) / len(_STRATEGIES))
            p(stage_lo, f"gmsh: try [{strat.name}]")
            try:
                _setup_strategy(gmsh, strat, target, diag)
                gmsh.model.add("job")

                if strat.source == "step":
                    p(stage_lo + (stage_hi - stage_lo) * 0.1, "gmsh: importing STEP")
                    gmsh.model.occ.importShapes(str(step_path))
                    if strat.heal:
                        p(stage_lo + (stage_hi - stage_lo) * 0.25, "gmsh: healing geometry")
                        try:
                            gmsh.model.occ.healShapes()
                        except Exception:
                            pass
                        try:
                            gmsh.model.occ.removeAllDuplicates()
                        except Exception:
                            pass
                    gmsh.model.occ.synchronize()
                else:
                    # STL discrete reconstruction
                    if not stl_built:
                        p(stage_lo + (stage_hi - stage_lo) * 0.05, "stl: building from OCP")
                        _build_stl_from_geometry(geometry, stl_path)
                        stl_built = True
                    p(stage_lo + (stage_hi - stage_lo) * 0.15, "gmsh: loading STL")
                    gmsh.merge(str(stl_path))
                    # Classify surfaces by feature angle (40deg) -> recover face structure
                    angle = 40.0 * np.pi / 180.0
                    gmsh.model.mesh.classifySurfaces(angle, True, True, np.pi)
                    gmsh.model.mesh.createGeometry()
                    # Assemble a Volume from all reconstructed surfaces
                    surfaces = [s for _d, s in gmsh.model.getEntities(2)]
                    if not surfaces:
                        raise RuntimeError("STL reconstruction produced no surfaces")
                    loop = gmsh.model.geo.addSurfaceLoop(surfaces)
                    gmsh.model.geo.addVolume([loop])
                    gmsh.model.geo.synchronize()

                face_id_to_tag = _map_faces_to_gmsh(gmsh, geometry, source=strat.source)
                bc_tags = _assign_bc_physical_groups(gmsh, bcs, face_id_to_tag)

                p(stage_lo + (stage_hi - stage_lo) * 0.4, "gmsh: meshing")
                gmsh.model.mesh.generate(3)
                if strat.order_at_gen == 1:
                    p(stage_lo + (stage_hi - stage_lo) * 0.8, "gmsh: elevating to order 2")
                    gmsh.model.mesh.setOrder(2)

                if not _has_tet10(gmsh):
                    raise RuntimeError("no tet10 elements produced")

                used = strat
                break

            except Exception as e:
                last_err = e
                try:
                    gmsh.clear()
                except Exception:
                    pass
                continue
        else:
            raise RuntimeError(
                f"All {len(_STRATEGIES)} meshing strategies failed. "
                f"Last error: {last_err}. "
                f"Try increasing mesh size, simplifying the CAD model "
                f"(remove sliver faces / fillets / chamfers), "
                f"or pre-cleaning the STEP in a CAD tool."
            )

        try:
            p(0.65, "gmsh: extracting mesh")
            node_tags_raw, coords_flat, _ = gmsh.model.mesh.getNodes()
            node_tags = np.asarray(node_tags_raw, dtype=np.int64)
            coords = np.asarray(coords_flat, dtype=np.float64).reshape(-1, 3)
            tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

            et_types, _et_tags, et_conn = gmsh.model.mesh.getElements(dim=3)
            tet_conn_idx: list[list[int]] = []
            for tcode, conn in zip(et_types, et_conn):
                if tcode != 11:
                    continue
                arr = np.asarray(conn, dtype=np.int64).reshape(-1, 10)
                for row in arr:
                    tet_conn_idx.append([tag_to_idx[int(x)] for x in row])
            if not tet_conn_idx:
                raise RuntimeError("gmsh produced no tet10 elements after extraction")
            tet_conn_arr = np.asarray(tet_conn_idx, dtype=np.int64)

            surface_tris: list[list[int]] = []
            for _dim, tag in gmsh.model.getEntities(2):
                st_types, _st_tags, st_conn = gmsh.model.mesh.getElements(dim=2, tag=tag)
                for stype, sconn in zip(st_types, st_conn):
                    if stype == 9:
                        arr = np.asarray(sconn, dtype=np.int64).reshape(-1, 6)
                        for row in arr:
                            surface_tris.append([
                                tag_to_idx[int(row[0])],
                                tag_to_idx[int(row[1])],
                                tag_to_idx[int(row[2])],
                            ])
                    elif stype == 2:
                        arr = np.asarray(sconn, dtype=np.int64).reshape(-1, 3)
                        for row in arr:
                            surface_tris.append([tag_to_idx[int(x)] for x in row])
            surface_tris_arr = (
                np.asarray(surface_tris, dtype=np.int64)
                if surface_tris
                else np.zeros((0, 3), dtype=np.int64)
            )

            bc_payloads = _collect_bc_payloads(gmsh, bcs, bc_tags, coords, tag_to_idx)

            p(0.80, "writing .inp")
            inp_path = out_dir / "job.inp"
            _write_inp(
                inp_path=inp_path,
                node_tags=node_tags,
                coords=coords,
                tet_conn=tet_conn_arr,
                tag_to_idx=tag_to_idx,
                bc_payloads=bc_payloads,
                material=material,
            )

            return MeshResult(
                inp_path=inp_path,
                node_count=int(node_tags.size),
                element_count=int(tet_conn_arr.shape[0]),
                node_tags=node_tags,
                node_coords=coords,
                tet_conn=tet_conn_arr,
                surface_tris=surface_tris_arr,
                strategy_used=used.name,
            )
        finally:
            try:
                gmsh.clear()
            except Exception:
                pass


def _setup_strategy(gmsh, strat: _Strategy, target: float, diag: float) -> None:
    """Reset gmsh state and configure options for this strategy attempt."""
    try:
        gmsh.clear()
    except Exception:
        pass
    gmsh.option.setNumber("General.Terminal", 0)

    if strat.source == "step" and strat.heal:
        tol = max(diag * strat.heal_tol_scale, 1e-6)
        gmsh.option.setNumber("Geometry.OCCAutoFix", 1)
        gmsh.option.setNumber("Geometry.OCCFixDegenerated", 1)
        gmsh.option.setNumber("Geometry.OCCFixSmallEdges", 1)
        gmsh.option.setNumber("Geometry.OCCFixSmallFaces", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
        gmsh.option.setNumber("Geometry.OCCMakeSolids", 1)
        gmsh.option.setNumber("Geometry.Tolerance", tol)
        gmsh.option.setNumber("Geometry.ToleranceBoolean", tol)
    elif strat.source == "step":
        gmsh.option.setNumber("Geometry.OCCAutoFix", 0)
        gmsh.option.setNumber("Geometry.OCCFixDegenerated", 0)
        gmsh.option.setNumber("Geometry.OCCFixSmallEdges", 0)
        gmsh.option.setNumber("Geometry.OCCFixSmallFaces", 0)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 0)

    # Mesh size — kept identical across strategies (per user requirement)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", target * 0.25)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", target)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

    # Algorithm choices for this attempt
    gmsh.option.setNumber("Mesh.ElementOrder", strat.order_at_gen)
    gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 0)
    gmsh.option.setNumber("Mesh.Algorithm", strat.algo2d)
    gmsh.option.setNumber("Mesh.Algorithm3D", strat.algo3d)
    # Allow some optimisation passes — improves robustness on bad input
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)


def _has_tet10(gmsh) -> bool:
    et_types, _, _ = gmsh.model.mesh.getElements(dim=3)
    return any(int(t) == 11 for t in et_types)


# --------------------------------------------------------------------- mapping

def _map_faces_to_gmsh(
    gmsh, geometry: GeometryPayload, source: str = "step"
) -> dict[int, int]:
    """Match OCP face_id -> gmsh surface tag via centroid nearest-neighbour.

    For STEP-imported entities, use OCC's exact center-of-mass.
    For STL-reconstructed entities, fall back to bounding-box center
    (OCC center is unavailable for non-OCC entities).
    """
    ocp_centroids: dict[int, np.ndarray] = {}
    for f in geometry.faces:
        pts = np.asarray(f.positions, dtype=np.float64).reshape(-1, 3)
        if pts.size == 0:
            continue
        ocp_centroids[f.face_id] = pts.mean(axis=0)

    gmsh_tags = [tag for _dim, tag in gmsh.model.getEntities(2)]
    gmsh_centroids: dict[int, np.ndarray] = {}
    for t in gmsh_tags:
        try:
            if source == "step":
                cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, t)
            else:
                xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(2, t)
                cx = (xmin + xmax) * 0.5
                cy = (ymin + ymax) * 0.5
                cz = (zmin + zmax) * 0.5
        except Exception:
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(2, t)
            cx = (xmin + xmax) * 0.5
            cy = (ymin + ymax) * 0.5
            cz = (zmin + zmax) * 0.5
        gmsh_centroids[t] = np.array([cx, cy, cz], dtype=np.float64)

    mapping: dict[int, int] = {}
    for fid, c in ocp_centroids.items():
        best_tag = -1
        best_d = float("inf")
        for t, gc in gmsh_centroids.items():
            d = float(np.linalg.norm(c - gc))
            if d < best_d:
                best_d = d
                best_tag = t
        if best_tag > 0:
            mapping[fid] = best_tag
    return mapping


def _build_stl_from_geometry(geometry: GeometryPayload, path: Path) -> None:
    """Write the OCP per-face surface tessellation as a single ASCII STL.

    This reconstructs a watertight (assuming the OCP triangulation was complete)
    discrete surface that gmsh can re-mesh independent of the original STEP
    topology — useful for CAD with sliver faces, missing booleans, or
    extreme parameterisations that defeat OCC's mesher.
    """
    with open(path, "w", encoding="ascii") as f:
        f.write("solid model\n")
        for face in geometry.faces:
            pts = np.asarray(face.positions, dtype=np.float64).reshape(-1, 3)
            idx = np.asarray(face.indices, dtype=np.int64).reshape(-1, 3)
            for tri in idx:
                a, b, c = pts[tri[0]], pts[tri[1]], pts[tri[2]]
                n = np.cross(b - a, c - a)
                ln = float(np.linalg.norm(n))
                if ln < 1e-18:
                    continue
                n = n / ln
                f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
                f.write("    outer loop\n")
                f.write(f"      vertex {a[0]:.6e} {a[1]:.6e} {a[2]:.6e}\n")
                f.write(f"      vertex {b[0]:.6e} {b[1]:.6e} {b[2]:.6e}\n")
                f.write(f"      vertex {c[0]:.6e} {c[1]:.6e} {c[2]:.6e}\n")
                f.write("    endloop\n")
                f.write("  endfacet\n")
        f.write("endsolid model\n")


def _assign_bc_physical_groups(
    gmsh, bcs: list[BC], face_id_to_tag: dict[int, int]
) -> dict[int, int]:
    out: dict[int, int] = {}
    for i, bc in enumerate(bcs):
        tags = [face_id_to_tag[fid] for fid in bc.faceIds if fid in face_id_to_tag]
        if not tags:
            continue
        phys = gmsh.model.addPhysicalGroup(2, tags)
        gmsh.model.setPhysicalName(2, phys, f"BC{i}")
        out[i] = phys
    vol_tags = [t for _d, t in gmsh.model.getEntities(3)]
    if vol_tags:
        vp = gmsh.model.addPhysicalGroup(3, vol_tags)
        gmsh.model.setPhysicalName(3, vp, "SOLID")
    return out


# --------------------------------------------------------------------- BC calc

@dataclass
class BCPayload:
    idx: int
    bc: BC
    node_tags: np.ndarray
    area: float
    normal: np.ndarray


def _collect_bc_payloads(
    gmsh,
    bcs: list[BC],
    bc_tags: dict[int, int],
    coords: np.ndarray,
    tag_to_idx: dict[int, int],
) -> list[BCPayload]:
    out: list[BCPayload] = []
    for i, bc in enumerate(bcs):
        phys = bc_tags.get(i)
        if phys is None:
            continue
        node_tags_raw, _c = gmsh.model.mesh.getNodesForPhysicalGroup(2, phys)
        node_tags = np.asarray(node_tags_raw, dtype=np.int64)

        area = 0.0
        normal = np.zeros(3, dtype=np.float64)
        if isinstance(bc, LoadBC):
            entities = gmsh.model.getEntitiesForPhysicalGroup(2, phys)
            for ent in entities:
                stypes, _st_tags, sconn = gmsh.model.mesh.getElements(dim=2, tag=int(ent))
                for stype, sc in zip(stypes, sconn):
                    if stype in (2, 9):
                        ncol = 3 if stype == 2 else 6
                        arr = np.asarray(sc, dtype=np.int64).reshape(-1, ncol)
                        for row in arr:
                            ia = tag_to_idx[int(row[0])]
                            ib = tag_to_idx[int(row[1])]
                            ic = tag_to_idx[int(row[2])]
                            pa, pb, pc = coords[ia], coords[ib], coords[ic]
                            cross = np.cross(pb - pa, pc - pa)
                            a = 0.5 * float(np.linalg.norm(cross))
                            area += a
                            if a > 0:
                                normal += 0.5 * cross
            n_len = float(np.linalg.norm(normal))
            if n_len > 1e-18:
                normal /= n_len

        out.append(BCPayload(idx=i, bc=bc, node_tags=node_tags, area=area, normal=normal))
    return out


# --------------------------------------------------------------------- writer

def _write_inp(
    *,
    inp_path: Path,
    node_tags: np.ndarray,
    coords: np.ndarray,
    tet_conn: np.ndarray,
    tag_to_idx: dict[int, int],
    bc_payloads: list[BCPayload],
    material: Material,
) -> None:
    lines: list[str] = []
    lines.append("*HEADING")
    lines.append("auto_cae job")

    lines.append("*NODE")
    for i, t in enumerate(node_tags):
        x, y, z = coords[i]
        lines.append(f"{int(t)}, {x:.9g}, {y:.9g}, {z:.9g}")

    lines.append("*ELEMENT, TYPE=C3D10, ELSET=SOLID")
    # Gmsh tet10 order (0-based): v0 v1 v2 v3  m01 m12 m20 m03 m23 m13
    # Abaqus C3D10  order (0-based): v0 v1 v2 v3  m01 m12 m20 m03 m13 m23
    # -> swap last two columns
    for e, row in enumerate(tet_conn, start=1):
        reordered = [row[0], row[1], row[2], row[3],
                     row[4], row[5], row[6], row[7],
                     row[9], row[8]]
        labels = [str(int(node_tags[idx])) for idx in reordered]
        lines.append(", ".join([str(e)] + labels))

    for bp in bc_payloads:
        lines.append(f"*NSET, NSET=BC{bp.idx}")
        _emit_list(lines, [int(x) for x in bp.node_tags.tolist()])

    lines.append("*MATERIAL, NAME=MAT1")
    lines.append("*ELASTIC")
    lines.append(f"{material.young:.6g}, {material.poisson:.4g}")
    lines.append("*DENSITY")
    lines.append(f"{material.density:.6g}")
    lines.append("*SOLID SECTION, ELSET=SOLID, MATERIAL=MAT1")

    lines.append("*STEP")
    lines.append("*STATIC")

    for bp in bc_payloads:
        if isinstance(bp.bc, FixBC):
            lines.append("*BOUNDARY")
            d = bp.bc.dofs
            if d.get("x"):
                lines.append(f"BC{bp.idx}, 1, 1, 0.")
            if d.get("y"):
                lines.append(f"BC{bp.idx}, 2, 2, 0.")
            if d.get("z"):
                lines.append(f"BC{bp.idx}, 3, 3, 0.")

    for bp in bc_payloads:
        if not isinstance(bp.bc, LoadBC):
            continue
        load = bp.bc
        n_nodes = int(bp.node_tags.size)
        if n_nodes == 0:
            continue

        if load.kind == "force":
            total_mag = float(load.magnitude)
        else:
            total_mag = float(load.magnitude) * float(bp.area)

        if load.direction == "normal":
            direction = -bp.normal if np.linalg.norm(bp.normal) > 0 else np.zeros(3)
        else:
            dx = float(load.direction.get("x", 0.0))
            dy = float(load.direction.get("y", 0.0))
            dz = float(load.direction.get("z", 0.0))
            v = np.array([dx, dy, dz], dtype=np.float64)
            n = float(np.linalg.norm(v))
            direction = v / n if n > 1e-18 else np.zeros(3)

        if float(np.linalg.norm(direction)) < 1e-18:
            continue

        fx, fy, fz = (direction * total_mag / n_nodes).tolist()

        lines.append("*CLOAD")
        for t in bp.node_tags.tolist():
            if abs(fx) > 0:
                lines.append(f"{int(t)}, 1, {fx:.9g}")
            if abs(fy) > 0:
                lines.append(f"{int(t)}, 2, {fy:.9g}")
            if abs(fz) > 0:
                lines.append(f"{int(t)}, 3, {fz:.9g}")

    lines.append("*NODE FILE")
    lines.append("U")
    lines.append("*EL FILE")
    lines.append("S")
    lines.append("*END STEP")

    inp_path.write_text("\n".join(lines) + "\n", encoding="ascii")


def _emit_list(lines: list[str], values: Iterable[int], per_line: int = 8) -> None:
    chunk: list[str] = []
    for v in values:
        chunk.append(str(v))
        if len(chunk) == per_line:
            lines.append(", ".join(chunk))
            chunk = []
    if chunk:
        lines.append(", ".join(chunk))
