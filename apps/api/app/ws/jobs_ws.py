"""WebSocket endpoint that streams job status at 250ms intervals until terminal."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import state

router = APIRouter()

TERMINAL = {"done", "failed", "cancelled"}


@router.websocket("/ws/jobs/{job_id}")
async def job_ws(ws: WebSocket, job_id: str) -> None:
    await ws.accept()
    last: tuple | None = None
    try:
        while True:
            j = state.get_job(job_id)
            if j is None:
                await ws.send_json({"error": "job not found"})
                await ws.close()
                return
            snapshot = (j.status, round(j.progress, 4), j.message, j.error)
            if snapshot != last:
                await ws.send_json(
                    {
                        "id": j.id,
                        "status": j.status,
                        "progress": j.progress,
                        "message": j.message,
                        "error": j.error,
                    }
                )
                last = snapshot
            if j.status in TERMINAL:
                await ws.close()
                return
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return
