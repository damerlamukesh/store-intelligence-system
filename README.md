# Store Intelligence System

End-to-end submission for the Purplle / Apex Retail Store Intelligence challenge. It turns CCTV input into structured visitor events, ingests them into a production-aware API, computes live store metrics, and serves a web dashboard.

## Run in 5 commands

```bash
git clone https://github.com/damerlamukesh/store-intelligence-system.git
cd store-intelligence-system
docker compose up --build
python scripts/generate_events.py --video-source "C:\Users\VARUN\Downloads\CCTV Footage-20260529T160731Z-3-00144614ea.zip"
python scripts/ingest_events.py
python scripts/live_feed.py --sleep 0.3
```

Open http://localhost:8000 for the live dashboard.

## API

- `POST /events/ingest`: batch ingest up to 500 events, idempotent by `event_id`, with partial success for malformed rows.
- `GET /stores/{id}/metrics`: unique visitors, conversion rate, dwell by zone, queue depth, abandonment.
- `GET /stores/{id}/funnel`: Entry to Zone Visit to Billing Queue to Purchase, session based.
- `GET /stores/{id}/heatmap`: zone frequency and average dwell normalized for rendering.
- `GET /stores/{id}/anomalies`: queue spikes, conversion drops, dead zones, with suggested actions.
- `GET /health`: feed freshness and stale-feed warning.

## Detection pipeline

`scripts/generate_events.py` reads the CCTV zip, file metadata, and sample bytes to produce deterministic visitor sessions that vary with the supplied footage. In production I would swap the `video-stat-simulator` adapter with YOLOv8 + ByteTrack + zone polygons. The event contract and downstream API do not change.

## Tests

```bash
pip install -r requirements.txt
coverage run -m pytest
coverage report
```
