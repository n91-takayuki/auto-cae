"""Generate a simple cantilever beam STEP file for testing.

Usage:
    python scripts\\make_test_step.py [output_path]

Default output: workdir\\sample_beam.step (100 x 10 x 5 mm box).
"""
from __future__ import annotations

import sys
from pathlib import Path

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer


def make_beam_step(out: Path, dx: float = 100.0, dy: float = 10.0, dz: float = 5.0) -> None:
    shape = BRepPrimAPI_MakeBox(dx, dy, dz).Shape()
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    if writer.Write(str(out)) != IFSelect_RetDone:
        raise RuntimeError(f"Failed to write STEP: {out}")


if __name__ == "__main__":
    default = Path(__file__).resolve().parents[1] / "workdir" / "sample_beam.step"
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    out.parent.mkdir(parents=True, exist_ok=True)
    make_beam_step(out)
    print(f"wrote: {out}")
