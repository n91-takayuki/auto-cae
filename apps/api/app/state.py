"""In-memory project + job store (single-process)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .cad.step_loader import GeometryPayload


@dataclass
class Project:
    id: str
    filename: str
    geometry: GeometryPayload
    step_path: str = ""
    bcs: list[dict] = field(default_factory=list)
    material: dict | None = None


_projects: dict[str, Project] = {}
_projects_lock = Lock()


def put(project: Project) -> None:
    with _projects_lock:
        _projects[project.id] = project


def get(project_id: str) -> Project | None:
    with _projects_lock:
        return _projects.get(project_id)


def all_ids() -> list[str]:
    with _projects_lock:
        return list(_projects.keys())


# ---------------------------------------------------------------- jobs

@dataclass
class Job:
    id: str
    project_id: str
    status: str = "queued"         # queued, meshing, solving, postprocess, done, failed, cancelled
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    result: dict[str, Any] | None = None
    updated_at: float = field(default_factory=time.time)


_jobs: dict[str, Job] = {}
_jobs_lock = Lock()


def put_job(job: Job) -> None:
    with _jobs_lock:
        _jobs[job.id] = job


def get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def update_job(job_id: str, **fields: Any) -> Job | None:
    with _jobs_lock:
        j = _jobs.get(job_id)
        if j is None:
            return None
        for k, v in fields.items():
            setattr(j, k, v)
        j.updated_at = time.time()
        return j
