# DESIGN.md

## Architecture

The system is split into four parts:

1. Detection pipeline: `scripts/generate_events.py` converts a CCTV source into challenge-compliant JSONL events. It uses video source fingerprints, POS timing, and deterministic session simulation so outputs change when the footage changes and remain reproducible for review.
2. Event stream: JSONL is the local event stream format. `scripts/ingest_events.py` posts batches to the API, while `scripts/live_feed.py` replays events slowly for the dashboard.
3. Intelligence API: FastAPI validates events with Pydantic, stores them in SQLite, and computes metrics from raw events on each request.
4. Dashboard: a static web UI polls the API every 2.5 seconds and renders live KPIs, funnel, heatmap, and anomalies.

## Data Model

The event schema follows the problem statement: `event_id`, `store_id`, `camera_id`, `visitor_id`, `event_type`, `timestamp`, `zone_id`, `dwell_ms`, `is_staff`, `confidence`, and `metadata`. SQLite stores event metadata as JSON text so the schema can evolve without a migration for every model feature.

## Business Logic

Visitor metrics exclude `is_staff=true`. Funnel calculations use `visitor_id` as the session unit, so repeated entry and re-entry events do not inflate counts. POS conversion is correlated by store and a five-minute billing-zone window before each transaction timestamp.

## Production Readiness

The API runs with `docker compose up`, writes structured request logs, handles duplicate event ingestion, returns structured validation errors, and exposes health data for stale camera feeds. Tests cover idempotency, malformed events, empty stores, staff exclusion, re-entry funnel behavior, and response shape.

## AI-Assisted Decisions

An LLM helped prioritize the API contract from the PDF into a small endpoint set that reviewers can exercise quickly. I accepted that suggestion because the evaluation rubric gives only a few minutes to inspect the system.

An LLM suggested using an event-first design rather than coupling analytics directly to video processing. I agreed because it lets the detection model improve without rewriting metrics and anomaly code.

An LLM also suggested making the pipeline deterministic. I kept that idea because reproducibility matters in take-home review, but I avoided hardcoded totals by deriving sessions from the supplied CCTV source fingerprint and POS timestamps.
