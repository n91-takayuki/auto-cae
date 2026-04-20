from __future__ import annotations

import shutil
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import ALLOWED_ORIGINS, CCX_PATH, WORKDIR
from .routers import jobs, projects
from .ws import jobs_ws

app = FastAPI(title="Auto-CAE API", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(jobs_ws.router)


@app.on_event("startup")
def _startup_gmsh() -> None:
    # Initialize gmsh in the main thread so its signal handler can register.
    # Background jobs reuse this singleton (see mesh.gmsh_runner).
    try:
        import gmsh

        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
    except Exception:
        pass


@app.on_event("shutdown")
def _shutdown_gmsh() -> None:
    try:
        import gmsh

        gmsh.finalize()
    except Exception:
        pass


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "python": sys.version.split()[0],
        "workdir": str(WORKDIR),
        "ccx": shutil.which(CCX_PATH) or CCX_PATH,
    }


@app.get("/api/capabilities")
def capabilities() -> dict:
    def has(mod: str) -> bool:
        try:
            __import__(mod)
            return True
        except Exception:
            return False

    return {
        "ocp": has("OCP.STEPControl"),
        "gmsh": has("gmsh"),
        "ccx": shutil.which(CCX_PATH) is not None,
    }
