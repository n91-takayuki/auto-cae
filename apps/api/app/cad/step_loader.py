"""STEP loader + face-wise tessellation using OCP (cadquery-ocp)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS


@dataclass
class FaceMesh:
    face_id: int
    positions: list[float]    # flat [x0,y0,z0, x1,y1,z1, ...]
    indices: list[int]        # flat triangle indices (into positions/3)
    tri_count: int


@dataclass
class GeometryPayload:
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    faces: list[FaceMesh]
    lin_deflection: float


def load_step(path: str | Path, lin_deflection_ratio: float = 0.002) -> GeometryPayload:
    """Read a STEP file and return per-face triangulated meshes.

    Tessellation deflection is chosen proportional to the shape bounding box
    diagonal (``lin_deflection_ratio``). Face IDs are the enumeration index
    returned by ``TopExp_Explorer`` (stable within a single load).
    """
    path = str(path)
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != IFSelect_RetDone:
        raise ValueError(f"Failed to read STEP file: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError("STEP produced empty shape")

    bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    diag = ((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) ** 0.5
    lin_deflection = max(diag * lin_deflection_ratio, 1e-3)

    BRepMesh_IncrementalMesh(shape, lin_deflection, False, 0.3, True)

    faces: list[FaceMesh] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    face_index = 0
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        mesh = _extract_face_mesh(face, face_index)
        if mesh is not None:
            faces.append(mesh)
        face_index += 1
        explorer.Next()

    return GeometryPayload(
        bbox_min=(xmin, ymin, zmin),
        bbox_max=(xmax, ymax, zmax),
        faces=faces,
        lin_deflection=lin_deflection,
    )


def _extract_face_mesh(face, face_id: int) -> FaceMesh | None:
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face, loc)
    if tri is None:
        return None

    transform = loc.Transformation()
    nb_nodes = tri.NbNodes()
    nb_tris = tri.NbTriangles()

    positions: list[float] = []
    for i in range(1, nb_nodes + 1):
        p = tri.Node(i).Transformed(transform)
        positions.extend((p.X(), p.Y(), p.Z()))

    reversed_face = face.Orientation() == TopAbs_REVERSED
    indices: list[int] = []
    for i in range(1, nb_tris + 1):
        n1, n2, n3 = tri.Triangle(i).Get()
        if reversed_face:
            indices.extend((n1 - 1, n3 - 1, n2 - 1))
        else:
            indices.extend((n1 - 1, n2 - 1, n3 - 1))

    return FaceMesh(
        face_id=face_id,
        positions=positions,
        indices=indices,
        tri_count=nb_tris,
    )
