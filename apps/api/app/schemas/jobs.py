from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class FixBC(BaseModel):
    type: Literal["fix"] = "fix"
    faceIds: list[int]
    dofs: dict[str, bool]  # {x,y,z}


class LoadApplicationFace(BaseModel):
    mode: Literal["face"] = "face"


class LoadApplicationPoint(BaseModel):
    mode: Literal["point"] = "point"
    point: list[float]  # [x, y, z] in mm (model space)


class LoadApplicationRegion(BaseModel):
    mode: Literal["region"] = "region"
    point: list[float]   # [x, y, z] in mm
    radius: float        # mm


LoadApplication = Annotated[
    Union[LoadApplicationFace, LoadApplicationPoint, LoadApplicationRegion],
    Field(discriminator="mode"),
]


class LoadBC(BaseModel):
    type: Literal["load"] = "load"
    faceIds: list[int]
    magnitude: float
    kind: Literal["force", "pressure"]
    direction: Union[Literal["normal"], dict[str, float]]
    application: LoadApplication = Field(default_factory=LoadApplicationFace)


BC = Union[FixBC, LoadBC]


class Material(BaseModel):
    name: str = "S45C"
    young: float = 206_000.0   # MPa
    poisson: float = 0.30
    density: float = 7.85e-9   # t/mm^3


class MeshOptions(BaseModel):
    element: Literal["tet10"] = "tet10"
    sizeFactor: float = 1.0  # 1.0 = auto (bbox-based)


class JobRequest(BaseModel):
    projectId: str
    bcs: list[BC]
    material: Material = Field(default_factory=Material)
    mesh: MeshOptions = Field(default_factory=MeshOptions)


JobStatus = Literal["queued", "meshing", "solving", "postprocess", "done", "failed", "cancelled"]


class JobDTO(BaseModel):
    id: str
    projectId: str
    status: JobStatus
    progress: float = 0.0
    message: str = ""
    error: str | None = None


class ResultSummary(BaseModel):
    nodeCount: int
    elementCount: int
    dispMax: float
    vonMisesMax: float
    vonMisesMin: float


class ResultDTO(BaseModel):
    jobId: str
    summary: ResultSummary
    # Per-node scalar arrays (flat). Indexing matches `nodes` order.
    nodes: list[float]         # [x0,y0,z0,...]  (undeformed, mm)
    disp: list[float]          # [dx0,dy0,dz0,...] (mm)
    vonMises: list[float]      # per-node (MPa)
    surfaceIndices: list[int]  # flat tri indices into nodes
