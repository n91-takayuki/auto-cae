from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from .. import state
from ..cad.step_loader import load_step
from ..config import WORKDIR
from ..schemas.geometry import FaceMeshDTO, GeometryDTO, ProjectDTO

router = APIRouter(prefix="/api/projects", tags=["projects"])

ACCEPTED_EXT = {".step", ".stp"}


@router.post("", response_model=ProjectDTO)
async def create_project(file: UploadFile) -> ProjectDTO:
    name = file.filename or "model.step"
    ext = Path(name).suffix.lower()
    if ext not in ACCEPTED_EXT:
        raise HTTPException(400, f"Unsupported file extension: {ext}")

    project_id = uuid.uuid4().hex[:12]
    project_dir = WORKDIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    stored_path = project_dir / f"input{ext}"
    stored_path.write_bytes(await file.read())

    try:
        geometry = load_step(stored_path)
    except Exception as e:
        raise HTTPException(422, f"Failed to parse STEP: {e}") from e

    project = state.Project(
        id=project_id, filename=name, geometry=geometry, step_path=str(stored_path)
    )
    state.put(project)

    return ProjectDTO(
        id=project_id,
        filename=name,
        faceCount=len(geometry.faces),
        triCount=sum(f.tri_count for f in geometry.faces),
        bboxMin=geometry.bbox_min,
        bboxMax=geometry.bbox_max,
    )


@router.get("/{project_id}/geometry", response_model=GeometryDTO)
def get_geometry(project_id: str) -> GeometryDTO:
    project = state.get(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    g = project.geometry
    return GeometryDTO(
        bboxMin=g.bbox_min,
        bboxMax=g.bbox_max,
        linDeflection=g.lin_deflection,
        faces=[
            FaceMeshDTO(
                faceId=f.face_id,
                positions=f.positions,
                indices=f.indices,
                triCount=f.tri_count,
            )
            for f in g.faces
        ],
    )


@router.get("/{project_id}", response_model=ProjectDTO)
def get_project(project_id: str) -> ProjectDTO:
    project = state.get(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    g = project.geometry
    return ProjectDTO(
        id=project.id,
        filename=project.filename,
        faceCount=len(g.faces),
        triCount=sum(f.tri_count for f in g.faces),
        bboxMin=g.bbox_min,
        bboxMax=g.bbox_max,
    )
