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
from ..schemas.jobs import (
    BC,
    FixBC,
    LoadApplicationPoint,
    LoadApplicationRegion,
    LoadBC,
    Material,
    MeshOptions,
)

ProgressFn = Callable[[float, str], None]

_GMSH_LOCK = Lock()


@dataclass
class MeshResult:
    inp_path: Path
    node_count: int
    element_count: int
    # per-node (1-based node tags compacted to 0-based array index)
    node_tags: np.ndarray       # int64, shape (N,)
    node_coords: np.ndarray     # float64, shape (N, 3)   in mm
    # tet10 connectivity, compacted node indices (0-based into node_coords)
    tet_conn: np.ndarray        # int64, shape (E, 10)
    # surface tri mesh for post-processing overlay (outer surface, linear triangles)
    surface_tris: np.ndarray    # int64, shape (T, 3)  (0-based into node_coords)


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

    face_id in ``bcs`` refers to the OCP face enumeration index. We map those to
    gmsh surface tags via centroid nearest-neighbour.
    """
    import gmsh

    def p(v: float, msg: str) -> None:
        if progress:
            progress(v, msg)

    with _GMSH_LOCK:
        # gmsh must be initialized once in the main thread (done at app startup).
        # Here we only reset per-job state.
        try:
            gmsh.clear()
        except Exception:
            pass
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            p(0.05, "gmsh: importing STEP")
            gmsh.model.add("job")
            gmsh.model.occ.importShapes(str(step_path))
            gmsh.model.occ.synchronize()

            # Characteristic size from bbox diagonal
            xmin, ymin, zmin = geometry.bbox_min
            xmax, ymax, zmax = geometry.bbox_max
            diag = float(
                ((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5
            )
            target = max(diag / 20.0 * options.sizeFactor, 1e-3)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", target * 0.25)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", target)
            gmsh.option.setNumber("Mesh.ElementOrder", 2)
            gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 6)     # Frontal-Delaunay
            gmsh.option.setNumber("Mesh.Algorithm3D", 1)   # Delaunay

            # Face mapping: OCP face_id -> gmsh surface tag via centroid match
            face_id_to_tag = _map_faces_to_gmsh(gmsh, geometry)

            # Assign physical groups per BC
            bc_tags = _assign_bc_physical_groups(gmsh, bcs, face_id_to_tag)

            p(0.15, "gmsh: meshing (tet10)")
            gmsh.model.mesh.generate(3)
            gmsh.model.mesh.setOrder(2)

            # Extract mesh
            p(0.45, "gmsh: extracting mesh")
            node_tags_raw, coords_flat, _ = gmsh.model.mesh.getNodes()
            node_tags = np.asarray(node_tags_raw, dtype=np.int64)
            coords = np.asarray(coords_flat, dtype=np.float64).reshape(-1, 3)

            # Build compact index map: original tag -> 0-based index
            tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

            # Volume elements (tet10 = type 11)
            et_types, et_tags, et_conn = gmsh.model.mesh.getElements(dim=3)
            tet_conn_idx: list[list[int]] = []
            for tcode, _tags, conn in zip(et_types, et_tags, et_conn):
                if tcode != 11:
                    continue
                arr = np.asarray(conn, dtype=np.int64).reshape(-1, 10)
                for row in arr:
                    tet_conn_idx.append([tag_to_idx[int(x)] for x in row])
            if not tet_conn_idx:
                raise RuntimeError("gmsh produced no tet10 elements")
            tet_conn_arr = np.asarray(tet_conn_idx, dtype=np.int64)

            # Outer surface triangles (for post-processing overlay).
            # Gather all 2D elements (tri6 = type 9) across all surfaces.
            surface_tris: list[list[int]] = []
            for dim, tag in gmsh.model.getEntities(2):
                st_types, _st_tags, st_conn = gmsh.model.mesh.getElements(dim=2, tag=tag)
                for stype, sconn in zip(st_types, st_conn):
                    if stype == 9:  # tri6
                        arr = np.asarray(sconn, dtype=np.int64).reshape(-1, 6)
                        for row in arr:
                            surface_tris.append([
                                tag_to_idx[int(row[0])],
                                tag_to_idx[int(row[1])],
                                tag_to_idx[int(row[2])],
                            ])
                    elif stype == 2:  # tri3
                        arr = np.asarray(sconn, dtype=np.int64).reshape(-1, 3)
                        for row in arr:
                            surface_tris.append([tag_to_idx[int(x)] for x in row])
            surface_tris_arr = (
                np.asarray(surface_tris, dtype=np.int64)
                if surface_tris
                else np.zeros((0, 3), dtype=np.int64)
            )

            # Per-BC node tag set and normal/area for load distribution
            bc_payloads = _collect_bc_payloads(gmsh, bcs, bc_tags, coords, tag_to_idx)

            p(0.70, "writing .inp")
            inp_path = out_dir / "job.inp"
            _write_inp(
                inp_path=inp_path,
                node_tags=node_tags,
                coords=coords,
                tet_conn=tet_conn_arr,  # already compact indices (0-based)
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
            )
        finally:
            # Don't finalize — we reuse the singleton.
            try:
                gmsh.clear()
            except Exception:
                pass


# --------------------------------------------------------------------- mapping

def _map_faces_to_gmsh(gmsh, geometry: GeometryPayload) -> dict[int, int]:
    """Match OCP face_id -> gmsh surface tag via centroid nearest-neighbour."""
    # OCP centroids
    ocp_centroids: dict[int, np.ndarray] = {}
    for f in geometry.faces:
        pts = np.asarray(f.positions, dtype=np.float64).reshape(-1, 3)
        if pts.size == 0:
            continue
        ocp_centroids[f.face_id] = pts.mean(axis=0)

    # gmsh centroids
    gmsh_tags = [tag for _dim, tag in gmsh.model.getEntities(2)]
    gmsh_centroids: dict[int, np.ndarray] = {}
    for t in gmsh_tags:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, t)
        gmsh_centroids[t] = np.array([cx, cy, cz], dtype=np.float64)

    # Nearest match (face count may not exactly equal — OCP might drop faces
    # with no triangulation; here we just look up per requested face_id).
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


def _assign_bc_physical_groups(
    gmsh, bcs: list[BC], face_id_to_tag: dict[int, int]
) -> dict[int, int]:
    """Create a physical group per BC (index in list). Returns bc_idx -> phys_tag."""
    out: dict[int, int] = {}
    for i, bc in enumerate(bcs):
        tags = [face_id_to_tag[fid] for fid in bc.faceIds if fid in face_id_to_tag]
        if not tags:
            continue
        phys = gmsh.model.addPhysicalGroup(2, tags)
        gmsh.model.setPhysicalName(2, phys, f"BC{i}")
        out[i] = phys
    # one physical volume for all solids so the *.inp gets element set
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
    node_tags: np.ndarray        # raw gmsh tags (1-based)
    area: float                  # mm^2 (0 if unused)
    normal: np.ndarray           # unit vector (3,) (zeros if unused)


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

        # For loads, compute surface area + area-weighted normal from tri6/tri3
        area = 0.0
        normal = np.zeros(3, dtype=np.float64)
        if isinstance(bc, LoadBC):
            # Gather this BC's surface triangles as (ia, ib, ic) compact indices
            tris: list[tuple[int, int, int]] = []
            entities = gmsh.model.getEntitiesForPhysicalGroup(2, phys)
            for ent in entities:
                stypes, _st_tags, sconn = gmsh.model.mesh.getElements(dim=2, tag=int(ent))
                for stype, sc in zip(stypes, sconn):
                    if stype in (2, 9):
                        ncol = 3 if stype == 2 else 6
                        arr = np.asarray(sc, dtype=np.int64).reshape(-1, ncol)
                        for row in arr:
                            tris.append(
                                (
                                    tag_to_idx[int(row[0])],
                                    tag_to_idx[int(row[1])],
                                    tag_to_idx[int(row[2])],
                                )
                            )

            # Area-weighted face normal (from *all* tris on this face)
            for ia, ib, ic in tris:
                cross = np.cross(coords[ib] - coords[ia], coords[ic] - coords[ia])
                a = 0.5 * float(np.linalg.norm(cross))
                if a > 0:
                    normal += 0.5 * cross
            n_len = float(np.linalg.norm(normal))
            if n_len > 1e-18:
                normal /= n_len

            # Apply application-mode filter on node_tags + recompute effective area
            node_tags, area = _filter_load_nodes(
                bc, node_tags, coords, tag_to_idx, tris
            )

        out.append(BCPayload(idx=i, bc=bc, node_tags=node_tags, area=area, normal=normal))
    return out


def _filter_load_nodes(
    bc: LoadBC,
    node_tags: np.ndarray,
    coords: np.ndarray,
    tag_to_idx: dict[int, int],
    tris: list[tuple[int, int, int]],
) -> tuple[np.ndarray, float]:
    """Restrict load nodes to the application mode and compute effective area.

    - face: all nodes, area = sum of all tris
    - point: single closest node on this face, area = 0 (pressure → 0 force)
    - region: nodes within radius, area = sum of tris whose all 3 verts are in region
    """
    app = bc.application

    if isinstance(app, LoadApplicationPoint):
        target = np.asarray(app.point, dtype=np.float64)
        # indices into coords for all nodes on this face
        idxs = np.fromiter(
            (tag_to_idx[int(t)] for t in node_tags.tolist()), dtype=np.int64
        )
        if idxs.size == 0:
            return node_tags, 0.0
        pts = coords[idxs]
        d2 = np.sum((pts - target) ** 2, axis=1)
        best = int(np.argmin(d2))
        return np.asarray([int(node_tags[best])], dtype=np.int64), 0.0

    if isinstance(app, LoadApplicationRegion):
        target = np.asarray(app.point, dtype=np.float64)
        r2 = float(app.radius) ** 2
        # Filter nodes
        keep: list[int] = []
        keep_idx_set: set[int] = set()
        for t in node_tags.tolist():
            ci = tag_to_idx[int(t)]
            if float(np.sum((coords[ci] - target) ** 2)) <= r2:
                keep.append(int(t))
                keep_idx_set.add(ci)
        if not keep:
            return np.zeros(0, dtype=np.int64), 0.0
        # Effective area: tris with all three corner nodes in region
        area = 0.0
        for ia, ib, ic in tris:
            if ia in keep_idx_set and ib in keep_idx_set and ic in keep_idx_set:
                cross = np.cross(coords[ib] - coords[ia], coords[ic] - coords[ia])
                area += 0.5 * float(np.linalg.norm(cross))
        return np.asarray(keep, dtype=np.int64), area

    # face (default)
    area = 0.0
    for ia, ib, ic in tris:
        cross = np.cross(coords[ib] - coords[ia], coords[ic] - coords[ia])
        area += 0.5 * float(np.linalg.norm(cross))
    return node_tags, area


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
    """Write a CalculiX-compatible Abaqus .inp.

    - Nodes are labelled with their original gmsh tag so set membership is stable.
    - A single element set SOLID is used with material MAT1.
    - Fix BCs emit *BOUNDARY on node sets per active DOF.
    - Load BCs are lumped to equal-split *CLOAD (force) or area-weighted
      normal CLOAD (pressure). This is an MVP simplification.
    """
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

    # Node sets per BC
    for bp in bc_payloads:
        lines.append(f"*NSET, NSET=BC{bp.idx}")
        _emit_list(lines, [int(x) for x in bp.node_tags.tolist()])

    # Material
    lines.append("*MATERIAL, NAME=MAT1")
    lines.append("*ELASTIC")
    lines.append(f"{material.young:.6g}, {material.poisson:.4g}")
    lines.append("*DENSITY")
    lines.append(f"{material.density:.6g}")
    lines.append("*SOLID SECTION, ELSET=SOLID, MATERIAL=MAT1")

    # Step
    lines.append("*STEP")
    lines.append("*STATIC")

    # Boundary conditions (fix)
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

    # Loads
    for bp in bc_payloads:
        if not isinstance(bp.bc, LoadBC):
            continue
        load = bp.bc
        n_nodes = int(bp.node_tags.size)
        if n_nodes == 0:
            continue

        # Determine total force vector (N)
        if load.kind == "force":
            total_mag = float(load.magnitude)
        else:  # pressure (MPa) — convert to total force by area
            total_mag = float(load.magnitude) * float(bp.area)

        # Direction unit vector
        if load.direction == "normal":
            direction = -bp.normal if np.linalg.norm(bp.normal) > 0 else np.zeros(3)
            # convention: positive magnitude pushes INTO the surface (inward)
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

    # Output requests for FRD
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
