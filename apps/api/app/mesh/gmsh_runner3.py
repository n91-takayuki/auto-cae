"""Gmsh meshing + CalculiX .inp writing with BC injection.

Each meshing strategy is executed in a fresh Python subprocess. This is
required because gmsh's OCC engine retains corrupted state after a failed
strategy attempt — even ``gmsh.finalize()`` + ``gmsh.initialize()`` does not
fully reset it within the same Python process. Strategies that succeed in
isolation silently produce zero elements when run after a failed strategy in
the same process. Subprocess isolation guarantees a clean OCC state per
attempt.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable

import numpy as np

from ..cad.step_loader import GeometryPayload
from ..schemas.jobs import BC, FixBC, LoadBC, Material, MeshOptions

ProgressFn = Callable[[float, str], None]

_GMSH_LOCK = Lock()
_WORKER_PATH = Path(__file__).parent / "_worker.py"


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
    repaired_count: int = 0
    repaired_centroids: list[tuple[float, float, float]] | None = None
    dropped_count: int = 0
    dropped_centroids: list[tuple[float, float, float]] | None = None
    repair_csv_path: Path | None = None


# Webサービス向けの高速化・厳選された戦略リスト
@dataclass(frozen=True)
class _Strategy:
    name: str
    algo2d: int         # Mesh.Algorithm
    algo3d: int         # Mesh.Algorithm3D
    order_at_gen: int   # 2=tet10, 1=tet4
    elevate: bool       # True -> elevate to tet10
    timeout_s: float    # NEW: Fail fast timeout for this specific strategy
    coarse_factor: float = 1.0    # Target mesh size multiplier
    ignore_topology: bool = False # God mode flag


_STRATEGIES: list[_Strategy] = [
    # 1. 最速パス (タイムアウト: 30秒)
    # 綺麗なCADなら一瞬で終わる。長考するようなら次へ即座にスキップ。
    _Strategy("Fast tet10 (HXT)", 6, 10, 2, True, timeout_s=30.0),
    
    # 2. ロバスト・1次要素パス (タイムアウト: 45秒)
    # 2次要素での曲面適応を諦め、Frontal法で直線エッジの四面体(tet4)を確実に取りに行く。
    _Strategy("Robust tet4 (Frontal)", 6, 4, 1, False, timeout_s=45.0),
    
    # 3. 粗メッシュパス (タイムアウト: 45秒)
    # メッシュサイズを強制的に2倍にし、MeshAdaptアルゴリズムで微小なCADエラーを飲み込む。
    _Strategy("Coarse tet4 (MeshAdapt 2x)", 1, 1, 1, False, timeout_s=45.0, coarse_factor=2.0),
    
    # 4. 最終奥義: God Mode (タイムアウト: 60秒)
    # トポロジー破綻とみなし、CADのポイントや曲線を完全に無視。
    # 許容誤差を極限まで広げ、メッシュサイズを10倍にして形状をブロックで強引に埋める。
    _Strategy("God Mode tet4 (Ignore Topology)", 1, 1, 1, False, timeout_s=60.0, coarse_factor=10.0, ignore_topology=True),
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
    """Run selected meshing strategies in a fresh subprocess; return on first success."""
    del geometry  # unused in parent

    def p(v: float, msg: str) -> None:
        if progress:
            progress(v, msg)

    if options.sizeMm is not None and options.sizeMm > 0:
        target = float(options.sizeMm)
    else:
        target = max(1.0 * options.sizeFactor, 1e-3)

    out_dir.mkdir(parents=True, exist_ok=True)
    input_json = out_dir / "_worker_input.json"

    last_err = "(no strategy ran)"
    with _GMSH_LOCK:
        for i, strat in enumerate(_STRATEGIES):
            stage_lo = 0.05 + 0.55 * (i / len(_STRATEGIES))
            stage_hi = 0.05 + 0.55 * ((i + 1) / len(_STRATEGIES))
            p(stage_lo, f"gmsh: try [{strat.name}]")

            payload = {
                "step_path": str(step_path),
                "out_dir": str(out_dir),
                "target": target,
                "strategy_name": strat.name,
                "bcs": [bc.model_dump() for bc in bcs],
                "material": material.model_dump(),
            }
            input_json.write_text(json.dumps(payload), encoding="utf-8")

            try:
                proc = subprocess.run(
                    [sys.executable, str(_WORKER_PATH), str(input_json)],
                    capture_output=True,
                    timeout=strat.timeout_s,  # Use strategy-specific fail-fast timeout
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired:
                # タイムアウトしたら即座に見切りをつけて次の戦略へ
                last_err = f"[{strat.name}] timed out after {strat.timeout_s:.0f}s"
                continue

            if proc.returncode == 0:
                p(stage_hi, f"loading mesh from worker [{strat.name}]")
                return _load_worker_outputs(out_dir, strat)

            err_lines = (proc.stderr or "").strip().splitlines()
            last_err = err_lines[-1] if err_lines else f"[{strat.name}] exit {proc.returncode}"
            continue

    raise RuntimeError(
        f"All meshing strategies failed. "
        f"Last error: {last_err}. "
        f"The CAD model topology is severely broken or contains features that cannot be meshed."
    )


def _load_worker_outputs(out_dir: Path, strat: "_Strategy") -> MeshResult:
    result_path = out_dir / "result.json"
    npz_path = out_dir / "mesh.npz"
    if not result_path.exists() or not npz_path.exists():
        raise RuntimeError("worker reported success but artifacts are missing")

    info = json.loads(result_path.read_text(encoding="utf-8"))
    data = np.load(npz_path)
    return MeshResult(
        inp_path=out_dir / "job.inp",
        node_count=int(info["node_count"]),
        element_count=int(info["element_count"]),
        node_tags=data["node_tags"],
        node_coords=data["node_coords"],
        tet_conn=data["tet_conn"],
        surface_tris=data["surface_tris"],
        strategy_used=str(info.get("strategy_used", strat.name)),
        repaired_count=int(info.get("repaired_count", 0)),
        repaired_centroids=[tuple(c) for c in info.get("repaired_centroids", [])],
        dropped_count=int(info.get("dropped_count", 0)),
        dropped_centroids=[tuple(c) for c in info.get("dropped_centroids", [])],
        repair_csv_path=out_dir / "mesh_repair.csv",
    )


def _setup_strategy(gmsh, strat: _Strategy, target: float) -> None:
    """Reset gmsh state and configure options for this strategy attempt."""
    try:
        gmsh.clear()
    except Exception:
        pass
    gmsh.option.setNumber("General.Terminal", 0)

    current_target = target * getattr(strat, "coarse_factor", 1.0)

    # Healing functions are completely disabled to save time, unless in God Mode
    # where we force extreme tolerances.
    if getattr(strat, "ignore_topology", False):
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Geometry.Tolerance", current_target * 0.5)
        gmsh.option.setNumber("Geometry.OCCAutoFix", 1)
        gmsh.option.setNumber("Geometry.OCCFixDegenerated", 1)
        gmsh.option.setNumber("Geometry.OCCFixSmallEdges", 1)
        gmsh.option.setNumber("Geometry.OCCFixSmallFaces", 1)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)
    else:
        gmsh.option.setNumber("Geometry.OCCAutoFix", 0)
        gmsh.option.setNumber("Geometry.OCCFixDegenerated", 0)
        gmsh.option.setNumber("Geometry.OCCFixSmallEdges", 0)
        gmsh.option.setNumber("Geometry.OCCFixSmallFaces", 0)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 0)

    if getattr(strat, "ignore_topology", False):
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", current_target)
    else:
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", current_target * 0.25)
        
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", current_target)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

    gmsh.option.setNumber("Mesh.ElementOrder", strat.order_at_gen)
    gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 0)
    gmsh.option.setNumber("Mesh.Algorithm", strat.algo2d)
    gmsh.option.setNumber("Mesh.Algorithm3D", strat.algo3d)
    
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)
    gmsh.option.setNumber("Mesh.OptimizeThreshold", 0.3)
    gmsh.option.setNumber("Mesh.HighOrderOptimize", 2)
    gmsh.option.setNumber("Mesh.HighOrderPassMax", 25)
    gmsh.option.setNumber("Mesh.HighOrderThresholdMin", 0.1)
    gmsh.option.setNumber("Mesh.HighOrderThresholdMax", 2.0)


# (Below are unchanged utility functions for quality checks and Abaqus INP writing)
def _has_tet10(gmsh) -> bool:
    et_types, _, _ = gmsh.model.mesh.getElements(dim=3)
    return any(int(t) == 11 for t in et_types)

def _has_tet4(gmsh) -> bool:
    et_types, _, _ = gmsh.model.mesh.getElements(dim=3)
    return any(int(t) == 4 for t in et_types)

def _check_quality(gmsh, max_bad_ratio: float = 0.005) -> tuple[bool, int, int]:
    et_types, et_tags, _ = gmsh.model.mesh.getElements(dim=3)
    total = 0
    bad = 0
    for code, tags in zip(et_types, et_tags):
        if int(code) != 11: continue
        tag_list = [int(t) for t in tags]
        total += len(tag_list)
        if not tag_list: continue
        try:
            q = gmsh.model.mesh.getElementQualities(tag_list, "minSJ")
            for v in q:
                if float(v) <= 0.0: bad += 1
        except Exception:
            return False, total, total
    if total == 0: return False, 0, 0
    return (bad / total) <= max_bad_ratio, total, bad

def _try_repair_high_order(gmsh) -> None:
    for method in ("HighOrderElastic", "HighOrder", "Netgen"):
        try:
            gmsh.model.mesh.optimize(method, force=True)
        except Exception: pass

_TET10_EDGE_MAP: tuple[tuple[int, int, int], ...] = ((4, 0, 1), (5, 1, 2), (6, 2, 0), (7, 0, 3), (8, 2, 3), (9, 1, 3))

def _flatten_bad_midside_nodes(gmsh, threshold: float = 1e-6) -> tuple[int, list[tuple[float, float, float]]]:
    try: tags_all, coords_flat, _ = gmsh.model.mesh.getNodes()
    except Exception: return 0, []
    coord_map: dict[int, np.ndarray] = {int(t): np.asarray(coords_flat[3 * i : 3 * i + 3], dtype=np.float64) for i, t in enumerate(tags_all)}
    et_types, et_tags, et_conn = gmsh.model.mesh.getElements(dim=3)
    repaired_centroids: list[tuple[float, float, float]] = []
    node_updates: dict[int, np.ndarray] = {}
    for code, tags, conn in zip(et_types, et_tags, et_conn):
        if int(code) != 11: continue
        tag_list = [int(t) for t in tags]
        if not tag_list: continue
        conn_arr = np.asarray(conn, dtype=np.int64).reshape(-1, 10)
        try: qual = gmsh.model.mesh.getElementQualities(tag_list, "minSJ")
        except Exception: qual = [0.0] * len(tag_list)
        for i, q in enumerate(qual):
            if float(q) > threshold: continue
            nodes = [int(x) for x in conn_arr[i]]
            pts = [coord_map.get(n) for n in nodes]
            if any(p is None for p in pts): continue
            centroid = np.mean(np.stack(pts), axis=0)
            repaired_centroids.append((float(centroid[0]), float(centroid[1]), float(centroid[2])))
            for mid_idx, a_idx, b_idx in _TET10_EDGE_MAP:
                mid_tag = nodes[mid_idx]
                if mid_tag in node_updates: continue
                a, b = coord_map[nodes[a_idx]], coord_map[nodes[b_idx]]
                node_updates[mid_tag] = 0.5 * (a + b)
    for tag, coord in node_updates.items():
        try: gmsh.model.mesh.setNode(int(tag), [float(coord[0]), float(coord[1]), float(coord[2])], [])
        except Exception: pass
    return len(repaired_centroids), repaired_centroids

def _collect_bad_element_centroids(gmsh, threshold: float = 0.0) -> list[tuple[float, float, float]]:
    try: tags_all, coords_flat, _ = gmsh.model.mesh.getNodes()
    except Exception: return []
    coord_map = {int(t): np.asarray(coords_flat[3 * i : 3 * i + 3], dtype=np.float64) for i, t in enumerate(tags_all)}
    et_types, et_tags, et_conn = gmsh.model.mesh.getElements(dim=3)
    out: list[tuple[float, float, float]] = []
    for code, tags, conn in zip(et_types, et_tags, et_conn):
        if int(code) != 11: continue
        tag_list = [int(t) for t in tags]
        if not tag_list: continue
        try: qual = gmsh.model.mesh.getElementQualities(tag_list, "minSJ")
        except Exception: continue
        conn_arr = np.asarray(conn, dtype=np.int64).reshape(-1, 10)
        for i, q in enumerate(qual):
            if float(q) > threshold: continue
            nodes = [int(x) for x in conn_arr[i]]
            pts = [coord_map[n] for n in nodes if n in coord_map]
            if not pts: continue
            c = np.mean(np.stack(pts), axis=0)
            out.append((float(c[0]), float(c[1]), float(c[2])))
    return out

def _write_repair_csv(path: Path, repaired: list[tuple[float, float, float]], dropped: list[tuple[float, float, float]]) -> None:
    with open(path, "w", encoding="ascii") as f:
        f.write("# mesh repair log (coords in mm)\nstatus,x,y,z\n")
        for x, y, z in repaired: f.write(f"repaired,{x:.6g},{y:.6g},{z:.6g}\n")
        for x, y, z in dropped: f.write(f"still_bad,{x:.6g},{y:.6g},{z:.6g}\n")

def _map_faces_to_gmsh(gmsh, geometry: GeometryPayload) -> dict[int, int]:
    ocp_centroids: dict[int, np.ndarray] = {}
    for f in geometry.faces:
        pts = np.asarray(f.positions, dtype=np.float64).reshape(-1, 3)
        if pts.size == 0: continue
        ocp_centroids[f.face_id] = pts.mean(axis=0)
    gmsh_tags = [tag for _dim, tag in gmsh.model.getEntities(2)]
    gmsh_centroids: dict[int, np.ndarray] = {}
    for t in gmsh_tags:
        try: cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, t)
        except Exception:
            try:
                xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(2, t)
                cx, cy, cz = (xmin + xmax) * 0.5, (ymin + ymax) * 0.5, (zmin + zmax) * 0.5
            except Exception: continue
        gmsh_centroids[t] = np.array([cx, cy, cz], dtype=np.float64)
    mapping: dict[int, int] = {}
    for fid, c in ocp_centroids.items():
        best_tag, best_d = -1, float("inf")
        for t, gc in gmsh_centroids.items():
            d = float(np.linalg.norm(c - gc))
            if d < best_d: best_d, best_tag = d, t
        if best_tag > 0: mapping[fid] = best_tag
    return mapping

def _assign_bc_physical_groups(gmsh, bcs: list[BC], face_id_to_tag: dict[int, int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for i, bc in enumerate(bcs):
        tags = [face_id_to_tag[fid] for fid in bc.faceIds if fid in face_id_to_tag]
        if not tags: continue
        phys = gmsh.model.addPhysicalGroup(2, tags)
        gmsh.model.setPhysicalName(2, phys, f"BC{i}")
        out[i] = phys
    vol_tags = [t for _d, t in gmsh.model.getEntities(3)]
    if vol_tags:
        vp = gmsh.model.addPhysicalGroup(3, vol_tags)
        gmsh.model.setPhysicalName(3, vp, "SOLID")
    return out

@dataclass
class BCPayload:
    idx: int
    bc: BC
    node_tags: np.ndarray
    area: float
    normal: np.ndarray

def _collect_bc_payloads(gmsh, bcs: list[BC], bc_tags: dict[int, int], coords: np.ndarray, tag_to_idx: dict[int, int]) -> list[BCPayload]:
    out: list[BCPayload] = []
    for i, bc in enumerate(bcs):
        phys = bc_tags.get(i)
        if phys is None: continue
        node_tags_raw, _c = gmsh.model.mesh.getNodesForPhysicalGroup(2, phys)
        node_tags = np.asarray(node_tags_raw, dtype=np.int64)
        area, normal = 0.0, np.zeros(3, dtype=np.float64)
        if isinstance(bc, LoadBC):
            entities = gmsh.model.getEntitiesForPhysicalGroup(2, phys)
            for ent in entities:
                stypes, _st_tags, sconn = gmsh.model.mesh.getElements(dim=2, tag=int(ent))
                for stype, sc in zip(stypes, sconn):
                    if stype in (2, 9):
                        ncol = 3 if stype == 2 else 6
                        arr = np.asarray(sc, dtype=np.int64).reshape(-1, ncol)
                        for row in arr:
                            ia, ib, ic = tag_to_idx[int(row[0])], tag_to_idx[int(row[1])], tag_to_idx[int(row[2])]
                            pa, pb, pc = coords[ia], coords[ib], coords[ic]
                            cross = np.cross(pb - pa, pc - pa)
                            area += 0.5 * float(np.linalg.norm(cross))
                            if 0.5 * float(np.linalg.norm(cross)) > 0: normal += 0.5 * cross
            n_len = float(np.linalg.norm(normal))
            if n_len > 1e-18: normal /= n_len
        out.append(BCPayload(idx=i, bc=bc, node_tags=node_tags, area=area, normal=normal))
    return out

def _write_inp(*, inp_path: Path, node_tags: np.ndarray, coords: np.ndarray, tet_conn: np.ndarray, bc_payloads: list[BCPayload], material: Material, element_order: int = 2) -> None:
    lines: list[str] = ["*HEADING", "auto_cae job", "*NODE"]
    for i, t in enumerate(node_tags):
        x, y, z = coords[i]
        lines.append(f"{int(t)}, {x:.9g}, {y:.9g}, {z:.9g}")
    if element_order == 2:
        lines.append("*ELEMENT, TYPE=C3D10, ELSET=SOLID")
        for e, row in enumerate(tet_conn, start=1):
            reordered = [row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[9], row[8]]
            labels = [str(int(node_tags[idx])) for idx in reordered]
            lines.append(", ".join([str(e)] + labels))
    else:
        lines.append("*ELEMENT, TYPE=C3D4, ELSET=SOLID")
        for e, row in enumerate(tet_conn, start=1):
            labels = [str(int(node_tags[idx])) for idx in row[:4]]
            lines.append(", ".join([str(e)] + labels))
    for bp in bc_payloads:
        lines.append(f"*NSET, NSET=BC{bp.idx}")
        _emit_list(lines, [int(x) for x in bp.node_tags.tolist()])
    lines.extend([
        "*MATERIAL, NAME=MAT1", "*ELASTIC", f"{material.young:.6g}, {material.poisson:.4g}",
        "*DENSITY", f"{material.density:.6g}", "*SOLID SECTION, ELSET=SOLID, MATERIAL=MAT1",
        "*STEP", "*STATIC"
    ])
    for bp in bc_payloads:
        if isinstance(bp.bc, FixBC):
            lines.append("*BOUNDARY")
            d = bp.bc.dofs
            if d.get("x"): lines.append(f"BC{bp.idx}, 1, 1, 0.")
            if d.get("y"): lines.append(f"BC{bp.idx}, 2, 2, 0.")
            if d.get("z"): lines.append(f"BC{bp.idx}, 3, 3, 0.")
    for bp in bc_payloads:
        if not isinstance(bp.bc, LoadBC): continue
        load = bp.bc
        n_nodes = int(bp.node_tags.size)
        if n_nodes == 0: continue
        total_mag = float(load.magnitude) if load.kind == "force" else float(load.magnitude) * float(bp.area)
        if load.direction == "normal":
            direction = -bp.normal if np.linalg.norm(bp.normal) > 0 else np.zeros(3)
        else:
            dx, dy, dz = float(load.direction.get("x", 0.0)), float(load.direction.get("y", 0.0)), float(load.direction.get("z", 0.0))
            v = np.array([dx, dy, dz], dtype=np.float64)
            n = float(np.linalg.norm(v))
            direction = v / n if n > 1e-18 else np.zeros(3)
        if float(np.linalg.norm(direction)) < 1e-18: continue
        fx, fy, fz = (direction * total_mag / n_nodes).tolist()
        lines.append("*CLOAD")
        for t in bp.node_tags.tolist():
            if abs(fx) > 0: lines.append(f"{int(t)}, 1, {fx:.9g}")
            if abs(fy) > 0: lines.append(f"{int(t)}, 2, {fy:.9g}")
            if abs(fz) > 0: lines.append(f"{int(t)}, 3, {fz:.9g}")
    lines.extend(["*NODE FILE", "U", "*EL FILE", "S", "*END STEP"])
    inp_path.write_text("\n".join(lines) + "\n", encoding="ascii")

def _emit_list(lines: list[str], values: Iterable[int], per_line: int = 8) -> None:
    chunk: list[str] = []
    for v in values:
        chunk.append(str(v))
        if len(chunk) == per_line:
            lines.append(", ".join(chunk))
            chunk = []
    if chunk: lines.append(", ".join(chunk))