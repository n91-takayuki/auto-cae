from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from .. import state
from ..schemas.jobs import FixBC, JobDTO, JobRequest, ResultDTO
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


def _to_dto(j: state.Job) -> JobDTO:
    return JobDTO(
        id=j.id,
        projectId=j.project_id,
        status=j.status,  # type: ignore[arg-type]
        progress=j.progress,
        message=j.message,
        error=j.error,
    )
