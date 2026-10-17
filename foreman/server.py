"""FastAPI app: REST controls, server-sent events, and the static control-room UI.

    uvicorn foreman.server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from .agent import Foreman
from .config import settings
from .telemetry import Telemetry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("foreman")


class Broadcaster:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subscribers: set[asyncio.Queue[str]] = set()

    def emit(self, event: str, data: dict[str, Any]) -> None:
        if not self.loop:
            return
        msg = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
        for q in list(self.subscribers):
            self.loop.call_soon_threadsafe(self._put, q, msg)

    @staticmethod
    def _put(q: asyncio.Queue[str], msg: str) -> None:
        if q.qsize() > 200:  # slow client: drop rather than grow unbounded
            return
        q.put_nowait(msg)


bus = Broadcaster()
telemetry = Telemetry()
foreman = Foreman(bus.emit)


async def _telemetry_pump() -> None:
    while True:
        await asyncio.sleep(2)
        bus.emit("telemetry", telemetry.snapshot())


@asynccontextmanager
async def lifespan(_: FastAPI):
    bus.loop = asyncio.get_running_loop()
    foreman.load_detector()
    foreman.start_threads()
    telemetry.start()
    task = asyncio.create_task(_telemetry_pump())
    log.info("Foreman up: llm=%s (%s) model=%s", settings.llm_base_url, settings.llm_mode, settings.llm_model)
    yield
    task.cancel()


app = FastAPI(title="Foreman", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def revalidate_ui(request, call_next):
    """UI files change on every redeploy: make browsers revalidate (cheap with ETags) instead of serving stale JS/CSS."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------------- API
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"detector": foreman.detector is not None, "llm": foreman.reasoner.health(), "telemetry": telemetry.snapshot()}


@app.get("/api/state")
def state() -> dict[str, Any]:
    return {**foreman.state(), "telemetry": telemetry.snapshot()}


@app.get("/api/events")
async def events() -> StreamingResponse:
    q: asyncio.Queue[str] = asyncio.Queue()
    bus.subscribers.add(q)

    async def stream():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.subscribers.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class InjectBody(BaseModel):
    fault: str


@app.post("/api/line/start")
def line_start() -> dict[str, Any]:
    foreman.set_running(True)
    return foreman.line_state()


@app.post("/api/line/stop")
def line_stop() -> dict[str, Any]:
    foreman.set_running(False)
    return foreman.line_state()


@app.post("/api/line/step")
def line_step() -> dict[str, Any]:
    """Advance one tick manually (useful for scripted demos and tests)."""
    foreman.step()
    return foreman.line_state()


@app.post("/api/line/inject")
def line_inject(body: InjectBody) -> dict[str, Any]:
    try:
        foreman.inject(body.fault)
    except KeyError:
        raise HTTPException(404, f"unknown fault '{body.fault}'")
    return foreman.line_state()


@app.post("/api/line/clear")
def line_clear() -> dict[str, Any]:
    foreman.clear_fault()
    return foreman.line_state()


@app.post("/api/inspect")
async def inspect_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    if foreman.detector is None:
        raise HTTPException(503, foreman.detector_error or "detector not ready")
    raw = await file.read()
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, "image too large (max 12 MB)")
    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(400, "not an image")
    return await asyncio.to_thread(foreman.inspect, image, "upload")


@app.get("/api/incidents/{incident_id}")
def incident(incident_id: int) -> dict[str, Any]:
    inc = foreman.store.get(incident_id)
    if not inc:
        raise HTTPException(404, "not found")
    inc["detection"].pop("_mock_hint", None)
    return inc


class ReviewBody(BaseModel):
    reviewer: str = "supervisor"
    note: str = ""


@app.post("/api/incidents/{incident_id}/approve")
def approve(incident_id: int, body: ReviewBody) -> dict[str, Any]:
    return _review(incident_id, True, body)


@app.post("/api/incidents/{incident_id}/reject")
def reject(incident_id: int, body: ReviewBody) -> dict[str, Any]:
    return _review(incident_id, False, body)


def _review(incident_id: int, approve_: bool, body: ReviewBody) -> dict[str, Any]:
    try:
        return foreman.review(incident_id, approve_, body.reviewer, body.note)
    except KeyError:
        raise HTTPException(404, "not found")
    except ValueError as e:
        raise HTTPException(409, str(e))


class AskBody(BaseModel):
    question: str
    incident_id: int | None = None


@app.post("/api/ask")
async def ask(body: AskBody) -> dict[str, Any]:
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    return await asyncio.to_thread(foreman.ask, body.question.strip()[:800], body.incident_id)


# ---------------------------------------------------------------------- UI
@app.get("/")
def index() -> FileResponse:
    return FileResponse(settings.web_dir / "index.html")


app.mount("/static", StaticFiles(directory=settings.web_dir), name="static")
