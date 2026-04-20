"""End-to-end job pipeline: mesh -> solve -> postprocess."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import state
from ..config import WORKDIR
from ..frd.parser import parse_frd
from ..mesh.gmsh_runner import mesh_and_write_inp
from ..schemas.jobs import BC, JobRequest, Material, MeshOptions, ResultDTO, ResultSummary
from .ccx_runner import run_ccx, CcxRunError


def _progress_factory(job_id: str, lo: float, hi: float):
    span = hi - lo

    def cb(v: float, msg: str) -> None:
        # v is 0..1 within the sub-phase
        state.update_job(job_id, progress=lo + span * max(0.0, min(1.0, v)), message=msg)

    return cb


def run_job(job_id: str, req: JobRequest) -> None:
    """Synchronous job pipeline. Intended to be called in a worker thread."""
    project = state.get(req.projectId)
    if project is None:
        state.update_job(job_id, status="failed", error=f"project not found: {req.projectId}")
        return

    job_dir = WORKDIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        # -- mesh --
        state.update_job(job_id, status="meshing", progress=0.02, message="meshing")
        mesh = mesh_and_write_inp(
            step_path=Path(project.step_path),
            out_dir=job_dir,
            geometry=project.geometry,
            bcs=req.bcs,
            material=req.material,
            options=req.mesh,
            progress=_progress_factory(job_id, 0.02, 0.35),
        )

        # -- solve --
        state.update_job(job_id, status="solving", progress=0.35, message="running ccx")
        try:
            ccx = run_ccx(mesh.inp_path, progress=_progress_factory(job_id, 0.35, 0.85))
        except CcxRunError as e:
            state.update_job(job_id, status="failed", error=str(e))
            return

        # -- postprocess --
        state.update_job(job_id, status="postprocess", progress=0.88, message="parsing FRD")
        frd = parse_frd(ccx.frd_path)

        # Map FRD node ids back to mesh node order (they match by tag)
        # Build id->row lookup in FRD:
        frd_index = {int(nid): i for i, nid in enumerate(frd.node_ids)}

        # Align to mesh node order (mesh.node_tags drives the output order)
        n = mesh.node_tags.size
        disp = np.zeros((n, 3), dtype=np.float64)
        vm = np.zeros(n, dtype=np.float64)
        for i, t in enumerate(mesh.node_tags):
            k = frd_index.get(int(t))
            if k is None:
                continue
            disp[i] = frd.disp[k]
            vm[i] = frd.von_mises[k]

        nodes_flat = mesh.node_coords.astype(np.float64).ravel().tolist()
        disp_flat = disp.ravel().tolist()
        vm_list = vm.tolist()
        tris_flat = mesh.surface_tris.ravel().astype(np.int64).tolist()

        disp_mag = float(np.linalg.norm(disp, axis=1).max()) if n > 0 else 0.0
        result = ResultDTO(
            jobId=job_id,
            summary=ResultSummary(
                nodeCount=int(n),
                elementCount=int(mesh.element_count),
                dispMax=disp_mag,
                vonMisesMax=float(vm.max()) if n else 0.0,
                vonMisesMin=float(vm.min()) if n else 0.0,
            ),
            nodes=nodes_flat,
            disp=disp_flat,
            vonMises=vm_list,
            surfaceIndices=tris_flat,
        )

        state.update_job(
            job_id,
            status="done",
            progress=1.0,
            message="done",
            result=result.model_dump(),
        )
    except Exception as e:  # pragma: no cover
        state.update_job(job_id, status="failed", error=f"{type(e).__name__}: {e}")
