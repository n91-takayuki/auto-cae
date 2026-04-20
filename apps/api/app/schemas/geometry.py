from __future__ import annotations

from pydantic import BaseModel, Field


class FaceMeshDTO(BaseModel):
    faceId: int
    positions: list[float] = Field(description="Flat xyz: [x0,y0,z0,x1,y1,z1,...]")
    indices: list[int] = Field(description="Flat triangle indices")
    triCount: int


class GeometryDTO(BaseModel):
    bboxMin: tuple[float, float, float]
    bboxMax: tuple[float, float, float]
    linDeflection: float
    faces: list[FaceMeshDTO]


class ProjectDTO(BaseModel):
    id: str
    filename: str
    faceCount: int
    triCount: int
    bboxMin: tuple[float, float, float]
    bboxMax: tuple[float, float, float]
