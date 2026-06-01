from __future__ import annotations

from datetime import UTC, datetime
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .analytics import compute_anomalies, compute_funnel, compute_heatmap, compute_metrics, health
from .layout import load_layout
from .models import HealthResponse, IngestError, IngestRequest, IngestResponse, StoreEvent
from .store import EventStore


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "store_intelligence.db"))
POS_PATH = Path(os.getenv("POS_PATH", DATA_DIR / "pos_transactions.csv"))
LAYOUT_PATH = Path(os.getenv("LAYOUT_PATH", DATA_DIR / "store_layout.json"))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("store-intelligence")

app = FastAPI(title="Store Intelligence API", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
store = EventStore(DB_PATH, POS_PATH)


@app.middleware("http")
async def structured_logging(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["x-trace-id"] = trace_id
        return response
    finally:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        path_parts = request.url.path.strip("/").split("/")
        store_id = path_parts[1] if len(path_parts) > 1 and path_parts[0] == "stores" else None
        logger.info(
            {
                "trace_id": trace_id,
                "store_id": store_id,
                "endpoint": request.url.path,
                "latency_ms": latency_ms,
                "status_code": status_code,
            }
        )


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(BASE_DIR / "app" / "static" / "index.html")


@app.get("/layout")
def get_layout() -> dict:
    return load_layout(LAYOUT_PATH)


@app.post("/events/ingest", response_model=IngestResponse)
async def ingest(payload: dict) -> IngestResponse:
    raw_events = payload.get("events", [])
    if not isinstance(raw_events, list) or not 1 <= len(raw_events) <= 500:
        raise HTTPException(status_code=422, detail={"error": "events must be a list of 1..500 items"})

    valid: list[StoreEvent] = []
    errors: list[IngestError] = []
    for index, raw in enumerate(raw_events):
        try:
            valid.append(StoreEvent.model_validate(raw))
        except ValidationError as exc:
            errors.append(
                IngestError(index=index, event_id=raw.get("event_id") if isinstance(raw, dict) else None, error=str(exc.errors()[0]))
            )

    try:
        accepted, duplicate = store.ingest(valid) if valid else (0, 0)
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"error": "EVENT_STORE_UNAVAILABLE", "message": str(exc)}) from exc
    logger.info({"endpoint": "/events/ingest", "event_count": len(raw_events), "accepted": accepted, "duplicate": duplicate, "failed": len(errors)})
    return IngestResponse(accepted=accepted, duplicate=duplicate, failed=len(errors), errors=errors)


@app.get("/stores/{store_id}/metrics")
def metrics(store_id: str) -> dict:
    return compute_metrics(store.events(store_id), store.pos(store_id)) | {"store_id": store_id, "computed_at": datetime.now(UTC).isoformat()}


@app.get("/stores/{store_id}/funnel")
def funnel(store_id: str) -> dict:
    return compute_funnel(store.events(store_id), store.pos(store_id)) | {"store_id": store_id}


@app.get("/stores/{store_id}/heatmap")
def heatmap_endpoint(store_id: str) -> dict:
    return compute_heatmap(store.events(store_id)) | {"store_id": store_id}


@app.get("/stores/{store_id}/anomalies")
def anomalies(store_id: str) -> dict:
    return {"store_id": store_id, "anomalies": compute_anomalies(store.events(store_id), store.pos(store_id))}


@app.get("/health", response_model=HealthResponse)
def health_endpoint() -> dict:
    result = health(store.last_event_by_store())
    if not result["stores"]:
        result["stores"] = {}
    return result
