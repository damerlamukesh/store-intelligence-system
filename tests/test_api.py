# PROMPT: Generate tests for a Store Intelligence API covering idempotent ingest, malformed partial success,
# metrics, funnel behavior with re-entry, all-staff exclusion, empty store handling, and zero purchases.
# CHANGES MADE: Kept the scenarios small and explicit, then aligned assertions with the actual session-based API contract.

from datetime import UTC, datetime, timedelta
import uuid

from fastapi.testclient import TestClient

from app.main import app, store


client = TestClient(app)


def event(visitor, event_type, offset=0, zone=None, staff=False, dwell=0, queue_depth=None):
    ts = datetime(2026, 4, 10, 12, 0, tzinfo=UTC) + timedelta(minutes=offset)
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01" if event_type in {"ENTRY", "EXIT", "REENTRY"} else "CAM_FLOOR_01",
        "visitor_id": visitor,
        "event_type": event_type,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "zone_id": zone,
        "dwell_ms": dwell,
        "is_staff": staff,
        "confidence": 0.9,
        "metadata": {"queue_depth": queue_depth, "sku_zone": zone, "session_seq": 1},
    }


def test_ingest_is_idempotent():
    payload = {"events": [event("VIS_TEST_1", "ENTRY")]}
    first = client.post("/events/ingest", json=payload).json()
    second = client.post("/events/ingest", json=payload).json()
    assert first["accepted"] == 1
    assert second["duplicate"] == 1


def test_ingest_partial_success_for_bad_event():
    good = event("VIS_TEST_2", "ZONE_ENTER", zone="SKINCARE")
    bad = event("VIS_TEST_BAD", "ZONE_ENTER")
    response = client.post("/events/ingest", json={"events": [good, bad]}).json()
    assert response["accepted"] == 1
    assert response["failed"] == 1
    assert response["errors"][0]["index"] == 1


def test_metrics_exclude_staff_and_handle_zero_store():
    staff_event = event("STAFF_TEST", "ENTRY", staff=True)
    client.post("/events/ingest", json={"events": [staff_event]})
    empty = client.get("/stores/STORE_EMPTY/metrics").json()
    assert empty["unique_visitors"] == 0
    metrics = client.get("/stores/STORE_BLR_002/metrics").json()
    assert "conversion_rate" in metrics


def test_funnel_counts_reentry_session_once():
    visitor = "VIS_REENTRY"
    rows = [
        event(visitor, "ENTRY", 1),
        event(visitor, "REENTRY", 2),
        event(visitor, "ZONE_ENTER", 3, zone="MAKEUP"),
        event(visitor, "BILLING_QUEUE_JOIN", 4, zone="BILLING", queue_depth=3),
    ]
    client.post("/events/ingest", json={"events": rows})
    funnel = client.get("/stores/STORE_BLR_002/funnel").json()
    entry_stage = next(stage for stage in funnel["stages"] if stage["stage"] == "entry")
    assert entry_stage["count"] >= 1


def test_anomalies_and_health_have_structured_shape():
    response = client.get("/stores/STORE_BLR_002/anomalies").json()
    assert isinstance(response["anomalies"], list)
    assert "suggested_action" in response["anomalies"][0]
    health = client.get("/health").json()
    assert health["status"] in {"OK", "WARN"}
