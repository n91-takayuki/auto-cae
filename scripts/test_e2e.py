"""End-to-end pipeline simulation for test.step."""
from __future__ import annotations
import sys, os, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

# Required env for ccx
os.environ.setdefault("CCX_PATH", r"C:\cae\ccx\ccx.exe")

import numpy as np
from app.cad.step_loader import load_step
from app.mesh.gmsh_runner import mesh_and_write_inp
from app.solve.ccx_runner import run_ccx
from app.frd.parser import parse_frd
from app.schemas.jobs import FixBC, LoadBC, Material, MeshOptions

step_path = ROOT / "test.step"
job_dir = ROOT / "workdir" / "_e2e"
if job_dir.exists():
    shutil.rmtree(job_dir)
job_dir.mkdir(parents=True)

g = load_step(str(step_path))
print(f"[OCP] {len(g.faces)} faces, ids: {[f.face_id for f in g.faces]}")

bcs = [
    FixBC(faceIds=[g.faces[0].face_id], dofs={"x": True, "y": True, "z": True}),
    LoadBC(
        faceIds=[g.faces[1].face_id],
        magnitude=100.0, kind="force", direction="normal",
    ),
]

mesh = mesh_and_write_inp(
    step_path=step_path, out_dir=job_dir,
    geometry=g, bcs=bcs,
    material=Material(), options=MeshOptions(sizeMm=5.0),
    progress=lambda v, m: None,
)
print(f"[mesh] strategy={mesh.strategy_used}, nodes={mesh.node_count}, elems={mesh.element_count}")
print(f"[mesh] node_tags type={type(mesh.node_tags).__name__}, dtype={mesh.node_tags.dtype}, size={mesh.node_tags.size}")
print(f"[mesh] node_tags head: {mesh.node_tags[:5]}, tail: {mesh.node_tags[-3:]}")

ccx = run_ccx(mesh.inp_path)
print(f"[ccx] frd: {ccx.frd_path}")

frd = parse_frd(ccx.frd_path)
print(f"[frd] nodes={len(frd.node_ids)}, |U|max={np.linalg.norm(frd.disp, axis=1).max():.4e}, vM_max={frd.von_mises.max():.4e}")
print(f"[frd] node_ids head: {frd.node_ids[:5]}, tail: {frd.node_ids[-3:]}")

# Mimic pipeline mapping
frd_index = {int(nid): i for i, nid in enumerate(frd.node_ids)}
n = mesh.node_tags.size
disp = np.zeros((n, 3))
vm = np.zeros(n)
hits = 0
for i, t in enumerate(mesh.node_tags):
    k = frd_index.get(int(t))
    if k is None:
        continue
    disp[i] = frd.disp[k]
    vm[i] = frd.von_mises[k]
    hits += 1

print(f"[mapping] hits={hits}/{n}")
print(f"[mapped] |U|max={np.linalg.norm(disp, axis=1).max():.4e}, vM_max={vm.max():.4e}, vM_min={vm.min():.4e}")
