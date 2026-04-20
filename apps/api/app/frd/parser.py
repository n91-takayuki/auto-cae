"""Minimal CalculiX FRD parser (DISP + STRESS -> von Mises).

FRD is Fortran fixed-width ASCII. We slice by column widths for robustness
(values can be negative without a preceding space in the classic format).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class FrdResults:
    node_ids: np.ndarray          # int64 (N,)
    node_coords: np.ndarray       # float64 (N, 3)
    disp: np.ndarray              # float64 (N, 3) — Ux, Uy, Uz
    stress: np.ndarray            # float64 (N, 6) — Sxx Syy Szz Sxy Syz Szx
    von_mises: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        sxx, syy, szz, sxy, syz, szx = [self.stress[:, i] for i in range(6)]
        vm = np.sqrt(
            0.5
            * (
                (sxx - syy) ** 2
                + (syy - szz) ** 2
                + (szz - sxx) ** 2
                + 6.0 * (sxy * sxy + syz * syz + szx * szx)
            )
        )
        self.von_mises = vm


def _fw(line: str, widths: list[int]) -> list[str]:
    out: list[str] = []
    pos = 0
    for w in widths:
        out.append(line[pos : pos + w])
        pos += w
    return out


def parse_frd(path: Path) -> FrdResults:
    text = Path(path).read_text(encoding="ascii", errors="replace").splitlines()

    node_ids: list[int] = []
    node_coords: list[tuple[float, float, float]] = []
    disp_map: dict[int, tuple[float, float, float]] = {}
    stress_map: dict[int, tuple[float, float, float, float, float, float]] = {}

    i = 0
    n = len(text)

    while i < n:
        line = text[i]
        s = line.rstrip()

        # Node block header: "    2C<count>..."
        if s.lstrip().startswith("2C"):
            i += 1
            # Read until "-3"
            while i < n:
                l = text[i]
                if l.strip().startswith("-3"):
                    i += 1
                    break
                if l.startswith(" -1"):
                    # " -1 <nodeid:I10> <x:E12.5> <y:E12.5> <z:E12.5>"
                    parts = _fw(l, [3, 10, 12, 12, 12])
                    nid = int(parts[1])
                    x = float(parts[2])
                    y = float(parts[3])
                    z = float(parts[4])
                    node_ids.append(nid)
                    node_coords.append((x, y, z))
                i += 1
            continue

        # Result block: lines starting with -4 declare the variable
        if s.startswith(" -4") or s.startswith("-4"):
            header_parts = s.split()
            # e.g. "-4  DISP        4    1"  or  "-4  STRESS      6    1"
            var_name = header_parts[1] if len(header_parts) > 1 else ""
            # Read "-5" component declarations (skip them) then "-1" data lines
            i += 1
            ncomp = 0
            while i < n:
                l = text[i]
                if l.strip().startswith("-5"):
                    ncomp += 1
                    i += 1
                    continue
                break

            # Now read -1 data until -3
            while i < n:
                l = text[i]
                sl = l.strip()
                if sl.startswith("-3"):
                    i += 1
                    break
                if l.startswith(" -1") or l.startswith("-1"):
                    widths = [3, 10] + [12] * ncomp
                    p = _fw(l, widths)
                    try:
                        nid = int(p[1])
                    except ValueError:
                        i += 1
                        continue
                    vals = []
                    for k in range(ncomp):
                        try:
                            vals.append(float(p[2 + k]))
                        except ValueError:
                            vals.append(0.0)

                    if var_name == "DISP" and ncomp >= 3:
                        disp_map[nid] = (vals[0], vals[1], vals[2])
                    elif var_name == "STRESS" and ncomp >= 6:
                        stress_map[nid] = (
                            vals[0], vals[1], vals[2], vals[3], vals[4], vals[5]
                        )
                i += 1
            continue

        i += 1

    if not node_ids:
        raise ValueError(f"FRD has no nodes: {path}")

    ids = np.asarray(node_ids, dtype=np.int64)
    coords = np.asarray(node_coords, dtype=np.float64)

    disp = np.zeros((ids.size, 3), dtype=np.float64)
    stress = np.zeros((ids.size, 6), dtype=np.float64)
    for i, nid in enumerate(ids):
        if (d := disp_map.get(int(nid))) is not None:
            disp[i] = d
        if (sv := stress_map.get(int(nid))) is not None:
            stress[i] = sv

    return FrdResults(node_ids=ids, node_coords=coords, disp=disp, stress=stress)
