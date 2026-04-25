from __future__ import annotations

import io
import uuid

import numpy as np
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from .. import state
from ..config import WORKDIR
from ..frd.parser import parse_frd
from ..schemas.jobs import FixBC, JobDTO, JobRequest, LoadBC, ResultDTO
from ..solve.pipeline import run_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobDTO])
def list_jobs(projectId: str | None = None) -> list[JobDTO]:
    with state._jobs_lock:  # type: ignore[attr-defined]
        jobs = list(state._jobs.values())  # type: ignore[attr-defined]
    if projectId:
        jobs = [j for j in jobs if j.project_id == projectId]
    jobs.sort(key=lambda j: j.updated_at, reverse=True)
    return [_to_dto(j) for j in jobs]


@router.post("", response_model=JobDTO)
def create_job(req: JobRequest, bg: BackgroundTasks) -> JobDTO:
    if not state.get(req.projectId):
        raise HTTPException(404, f"project not found: {req.projectId}")
    if not req.bcs:
        raise HTTPException(422, "at least one boundary condition is required")
    # Unit/BC sanity: need at least one Fix (otherwise rigid-body modes)
    if not any(isinstance(bc, FixBC) for bc in req.bcs):
        raise HTTPException(422, "at least one fix constraint is required")
    if not any(isinstance(bc, LoadBC) for bc in req.bcs):
        raise HTTPException(
            422,
            "at least one load is required (without a load the stress field is "
            "trivially zero)",
        )

    job_id = uuid.uuid4().hex[:12]
    job = state.Job(id=job_id, project_id=req.projectId, status="queued", progress=0.0)
    state.put_job(job)
    bg.add_task(run_job, job_id, req)
    return _to_dto(job)


@router.get("/{job_id}", response_model=JobDTO)
def get_job(job_id: str) -> JobDTO:
    j = state.get_job(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return _to_dto(j)


@router.get("/{job_id}/result", response_model=ResultDTO)
def get_result(job_id: str) -> ResultDTO:
    j = state.get_job(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    if j.status != "done" or j.result is None:
        raise HTTPException(409, f"job not finished (status={j.status})")
    return ResultDTO.model_validate(j.result)


@router.get("/{job_id}/repair-csv")
def download_repair_csv(job_id: str) -> FileResponse:
    j = state.get_job(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    path = WORKDIR / "jobs" / job_id / "mesh_repair.csv"
    if not path.exists():
        raise HTTPException(404, "no repair log (no bad elements detected)")
    return FileResponse(
        path=str(path),
        media_type="text/csv",
        filename=f"{job_id}_mesh_repair.csv",
    )


@router.get("/{job_id}/inp")
def download_inp(job_id: str) -> FileResponse:
    j = state.get_job(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    inp_path = WORKDIR / "jobs" / job_id / "job.inp"
    if not inp_path.exists():
        raise HTTPException(404, ".inp not found (job may not have reached solve stage)")
    return FileResponse(
        path=str(inp_path),
        media_type="text/plain",
        filename=f"{job_id}.inp",
    )


@router.get("/{job_id}/csv")
def download_csv(job_id: str) -> StreamingResponse:
    """Per-node CSV: coords (mm), displacement (mm), stress tensor + von Mises (MPa)."""
    j = state.get_job(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    if j.status != "done":
        raise HTTPException(409, f"job not finished (status={j.status})")

    frd_path = WORKDIR / "jobs" / job_id / "job.frd"
    if not frd_path.exists():
        raise HTTPException(404, "FRD file not found")

    frd = parse_frd(frd_path)

    buf = io.StringIO()
    buf.write("# auto_cae job " + job_id + "\n")
    buf.write("# coords [mm], displacement [mm], stress [MPa]\n")
    buf.write(
        "node_id,x,y,z,ux,uy,uz,|U|,sxx,syy,szz,sxy,syz,szx,von_mises\n"
    )
    disp_mag = np.linalg.norm(frd.disp, axis=1)
    rows = np.column_stack([
        frd.node_ids.astype(np.float64),
        frd.node_coords,                    # x y z
        frd.disp,                           # ux uy uz
        disp_mag,                           # |U|
        frd.stress,                         # sxx syy szz sxy syz szx
        frd.von_mises,                      # von_mises
    ])
    for row in rows:
        nid = int(row[0])
        vals = ",".join(f"{v:.6g}" for v in row[1:])
        buf.write(f"{nid},{vals}\n")

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.csv"'},
    )


def _to_dto(j: state.Job) -> JobDTO:
    return JobDTO(
        id=j.id,
        projectId=j.project_id,
        status=j.status,  # type: ignore[arg-type]
        progress=j.progress,
        message=j.message,
        error=j.error,
    )
