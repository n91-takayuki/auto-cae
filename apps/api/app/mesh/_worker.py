"""Subprocess worker: runs ONE meshing strategy in a fresh Python process.

Reads ``input.json`` (path on argv[1]) and writes:
  - job.inp           CalculiX input file
  - mesh.npz          node_tags, node_coords, tet_conn, surface_tris
  - mesh_repair.csv   per-element repair log
  - result.json       stats (counts, strategy used, repair info)

Exits 0 on success, 1 on mesh-stage failure, 2 on usage/setup error.

Required because gmsh's OCC engine retains corrupted internal state across
strategy attempts within a single Python process; subprocess isolation is the
only reliable way to reset it.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure we can import app.* when launched directly (not via -m)
_HERE = Path(__file__).resolve()
_APP_API_ROOT = _HERE.parents[2]   # .../apps/api
if str(_APP_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_API_ROOT))

import numpy as np  # noqa: E402

from app.cad.step_loader import load_step  # noqa: E402
from app.mesh import gmsh_runner as gr  # noqa: E402
from app.schemas.jobs import FixBC, LoadBC, Material  # noqa: E402


def _build_bc(d: dict):
    if d.get("type") == "fix":
        return FixBC.model_validate(d)
    if d.get("type") == "load":
        return LoadBC.model_validate(d)
    raise ValueError(f"unknown BC type: {d!r}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: _worker.py <input.json>", file=sys.stderr)
        return 2

    args = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    step_path = Path(args["step_path"])
    out_dir = Path(args["out_dir"])
    target = float(args["target"])
    strategy_name = str(args["strategy_name"])

    strat = next((s for s in gr._STRATEGIES if s.name == strategy_name), None)
    if strat is None:
        print(f"unknown strategy: {strategy_name!r}", file=sys.stderr)
        return 2

    try:
        bcs = [_build_bc(d) for d in args["bcs"]]
        material = Material.model_validate(args["material"])
    except Exception as e:
        print(f"input parse error: {e}", file=sys.stderr)
        return 2

    import gmsh

    try:
        geometry = load_step(str(step_path))
    except Exception as e:
        print(f"step load failed: {e}", file=sys.stderr)
        return 1

    gmsh.initialize()
    try:
        gr._setup_strategy(gmsh, strat, target)
        gmsh.model.add("job")
        gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()

        face_id_to_tag = gr._map_faces_to_gmsh(gmsh, geometry)
        bc_tags = gr._assign_bc_physical_groups(gmsh, bcs, face_id_to_tag)

        gmsh.model.mesh.generate(3)
        if strat.elevate:
            gmsh.model.mesh.setOrder(2)

        if strat.elevate and not gr._has_tet10(gmsh):
            print(f"[{strategy_name}] no tet10 elements produced", file=sys.stderr)
            return 1
        if not strat.elevate and not gr._has_tet4(gmsh):
            print(f"[{strategy_name}] no tet4 elements produced", file=sys.stderr)
            return 1

        rep_centroids: list[tuple[float, float, float]] = []
        drop_centroids: list[tuple[float, float, float]] = []

        if strat.elevate:
            n_rep, rep_centroids = gr._flatten_bad_midside_nodes(gmsh)
            if n_rep > 0:
                gr._try_repair_high_order(gmsh)
            ok, total, bad = gr._check_quality(gmsh)
            if not ok:
                drop_centroids = gr._collect_bad_element_centroids(gmsh)
                if total == 0 or bad / total > 0.01:
                    print(
                        f"[{strategy_name}] residual bad {bad}/{total} after repair",
                        file=sys.stderr,
                    )
                    return 1

        # ---- extract mesh ----
        node_tags_raw, coords_flat, _ = gmsh.model.mesh.getNodes()
        node_tags = np.asarray(node_tags_raw, dtype=np.int64)
        coords = np.asarray(coords_flat, dtype=np.float64).reshape(-1, 3)
        tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

        target_code = 11 if strat.elevate else 4
        n_cols = 10 if strat.elevate else 4
        et_types, _et_tags, et_conn = gmsh.model.mesh.getElements(dim=3)
        tet_conn_idx: list[list[int]] = []
        for tcode, conn in zip(et_types, et_conn):
            if int(tcode) != target_code:
                continue
            arr = np.asarray(conn, dtype=np.int64).reshape(-1, n_cols)
            for row in arr:
                tet_conn_idx.append([tag_to_idx[int(x)] for x in row])
        if not tet_conn_idx:
            print(
                f"[{strategy_name}] no {'tet10' if strat.elevate else 'tet4'} after extraction",
                file=sys.stderr,
            )
            return 1
        tet_conn_arr = np.asarray(tet_conn_idx, dtype=np.int64)

        surface_tris: list[list[int]] = []
        for _dim, tag in gmsh.model.getEntities(2):
            st_types, _st_tags, st_conn = gmsh.model.mesh.getElements(dim=2, tag=tag)
            for stype, sconn in zip(st_types, st_conn):
                if stype == 9:
                    arr = np.asarray(sconn, dtype=np.int64).reshape(-1, 6)
                    for row in arr:
                        surface_tris.append(
                            [tag_to_idx[int(row[k])] for k in (0, 1, 2)]
                        )
                elif stype == 2:
                    arr = np.asarray(sconn, dtype=np.int64).reshape(-1, 3)
                    for row in arr:
                        surface_tris.append([tag_to_idx[int(x)] for x in row])
        surface_tris_arr = (
            np.asarray(surface_tris, dtype=np.int64)
            if surface_tris
            else np.zeros((0, 3), dtype=np.int64)
        )

        bc_payloads = gr._collect_bc_payloads(gmsh, bcs, bc_tags, coords, tag_to_idx)

        # ---- write artifacts ----
        out_dir.mkdir(parents=True, exist_ok=True)
        inp_path = out_dir / "job.inp"
        gr._write_inp(
            inp_path=inp_path,
            node_tags=node_tags,
            coords=coords,
            tet_conn=tet_conn_arr,
            bc_payloads=bc_payloads,
            material=material,
            element_order=2 if strat.elevate else 1,
        )

        gr._write_repair_csv(out_dir / "mesh_repair.csv", rep_centroids, drop_centroids)

        np.savez(
            out_dir / "mesh.npz",
            node_tags=node_tags,
            node_coords=coords,
            tet_conn=tet_conn_arr,
            surface_tris=surface_tris_arr,
        )

        (out_dir / "result.json").write_text(
            json.dumps(
                {
                    "node_count": int(node_tags.size),
                    "element_count": int(tet_conn_arr.shape[0]),
                    "strategy_used": strat.name,
                    "elevate": bool(strat.elevate),
                    "repaired_count": len(rep_centroids),
                    "repaired_centroids": rep_centroids,
                    "dropped_count": len(drop_centroids),
                    "dropped_centroids": drop_centroids,
                }
            ),
            encoding="utf-8",
        )

        print(f"[{strategy_name}] OK")
        return 0

    except Exception as e:
        print(f"[{strategy_name}] {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        try:
            gmsh.finalize()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
