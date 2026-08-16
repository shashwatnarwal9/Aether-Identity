"""FastAPI server: Aether Identity pages + event ingestion, identity, audit, replay APIs."""
import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from engine import IdentityEngine

app = FastAPI(title="Aether Identity — Identity Resolution Engine")
engine = IdentityEngine(os.environ.get("IDRES_DB", "identity.duckdb"))
# ponytail: global lock (DuckDB conn is single-threaded); per-request pool if throughput matters
lock = threading.Lock()

FRONTEND = Path(__file__).parent / "frontend"
STATUS_CODES = {"accepted": 200, "duplicate": 409, "rejected": 422}


# --- Ingestion (PRD-mandated path) ---

@app.post("/events")
async def post_event(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "rejected", "reason": "invalid JSON body"}, status_code=422)
    with lock:
        result = engine.ingest(body)
    return JSONResponse(result, status_code=STATUS_CODES[result["status"]])


# --- Read/replay APIs ---

@app.get("/api/identities")
def identities():
    with lock:
        return engine.identities()


@app.get("/api/identities/{canonical_id}")
def identity(canonical_id: str):
    with lock:
        detail = engine.identity_detail(canonical_id)
    if detail is None:
        return JSONResponse({"error": "identity not found"}, status_code=404)
    return detail


@app.get("/api/audit")
def audit():
    with lock:
        return {"decisions": engine.audit_trail_enriched(), "rejections": engine.rejections()}


@app.get("/api/decision/{seq}")
def decision(seq: int):
    with lock:
        detail = engine.decision(seq)
    if detail is None:
        return JSONResponse({"error": "decision not found"}, status_code=404)
    return detail


@app.get("/api/events")
def events():
    with lock:
        return engine.raw_events()


@app.post("/api/replay")
def replay():
    """Re-run the stored event log through a fresh engine; verify decisions reproduce."""
    with lock:
        return engine.replay_from_log(include_trail=True)


@app.get("/api/audit/export")
def audit_export():
    with lock:
        payload = {"decisions": engine.audit_trail_enriched(),
                   "rejections": engine.rejections(),
                   "identities": engine.identities(),
                   "replay_verification": engine.replay_from_log()}
    return Response(json.dumps(payload, indent=2, sort_keys=True),
                    media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=aether-audit-report.json"})


# --- Pages ---

@app.get("/")
def landing():
    return FileResponse(FRONTEND / "index.html")


@app.get("/dashboard")
def dashboard():
    return FileResponse(FRONTEND / "dashboard.html")


@app.get("/audit")
def audit_page():
    return FileResponse(FRONTEND / "audit.html")


@app.get("/replay")
def replay_page():
    return FileResponse(FRONTEND / "replay.html")


@app.get("/static/{name}")
def static_file(name: str):
    path = (FRONTEND / name).resolve()
    if path.parent != FRONTEND.resolve() or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)
