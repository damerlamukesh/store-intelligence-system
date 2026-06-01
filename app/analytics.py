from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from .store import correlate_purchases, parse_ts


def _customer_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if not event["is_staff"]]


def _visitor_sessions(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in _customer_events(events):
        sessions[event["visitor_id"]].append(event)
    return sessions


def compute_metrics(events: list[dict[str, Any]], pos_rows: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = _visitor_sessions(events)
    visitors = set(sessions)
    converted = correlate_purchases(events, pos_rows)
    dwell_by_zone: dict[str, list[int]] = defaultdict(list)
    queue_depths: list[int] = []
    queue_joiners: set[str] = set()

    for event in _customer_events(events):
        if event["event_type"] == "ZONE_DWELL" and event["zone_id"]:
            dwell_by_zone[event["zone_id"]].append(event["dwell_ms"])
        if event["event_type"] == "BILLING_QUEUE_JOIN":
            queue_joiners.add(event["visitor_id"])
            depth = event["metadata"].get("queue_depth")
            if depth is not None:
                queue_depths.append(int(depth))

    avg_dwell = {
        zone: round(mean(values) / 1000, 2)
        for zone, values in sorted(dwell_by_zone.items())
        if values
    }
    abandoned = queue_joiners - converted
    return {
        "unique_visitors": len(visitors),
        "converted_visitors": len(converted),
        "transactions": len(pos_rows),
        "conversion_rate": round(len(converted) / len(visitors), 4) if visitors else 0,
        "avg_dwell_seconds_by_zone": avg_dwell,
        "current_queue_depth": queue_depths[-1] if queue_depths else 0,
        "max_queue_depth": max(queue_depths) if queue_depths else 0,
        "abandonment_rate": round(len(abandoned) / len(queue_joiners), 4) if queue_joiners else 0,
    }


def compute_funnel(events: list[dict[str, Any]], pos_rows: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = _visitor_sessions(events)
    converted = correlate_purchases(events, pos_rows)

    entered = {
        visitor_id
        for visitor_id, rows in sessions.items()
        if any(row["event_type"] in {"ENTRY", "REENTRY"} for row in rows)
    }
    zone_visit = {
        visitor_id
        for visitor_id, rows in sessions.items()
        if any(row["event_type"] in {"ZONE_ENTER", "ZONE_DWELL"} and row["zone_id"] != "BILLING" for row in rows)
    }
    billing = {
        visitor_id
        for visitor_id, rows in sessions.items()
        if any(row["event_type"] == "BILLING_QUEUE_JOIN" for row in rows)
    }
    stages = [
        ("entry", entered),
        ("zone_visit", zone_visit),
        ("billing_queue", billing),
        ("purchase", converted),
    ]
    previous = None
    response = []
    for name, visitor_ids in stages:
        count = len(visitor_ids)
        drop_off = 0 if previous is None or previous == 0 else round((previous - count) / previous, 4)
        response.append({"stage": name, "count": count, "drop_off_from_previous": max(drop_off, 0)})
        previous = count
    return {"unit": "visitor_session", "stages": response}


def compute_heatmap(events: list[dict[str, Any]]) -> dict[str, Any]:
    visits: Counter[str] = Counter()
    dwell: dict[str, list[int]] = defaultdict(list)
    sessions = _visitor_sessions(events)
    for event in _customer_events(events):
        zone = event["zone_id"]
        if not zone or zone == "ENTRY":
            continue
        if event["event_type"] in {"ZONE_ENTER", "BILLING_QUEUE_JOIN"}:
            visits[zone] += 1
        if event["event_type"] == "ZONE_DWELL":
            dwell[zone].append(event["dwell_ms"])
    max_visits = max(visits.values(), default=1)
    zones = sorted(set(visits) | set(dwell))
    return {
        "data_confidence": "LOW" if len(sessions) < 20 else "HIGH",
        "session_count": len(sessions),
        "zones": [
            {
                "zone_id": zone,
                "visits": visits[zone],
                "avg_dwell_seconds": round(mean(dwell[zone]) / 1000, 2) if dwell[zone] else 0,
                "heat": round((visits[zone] / max_visits) * 100, 2),
            }
            for zone in zones
        ],
    }


def compute_anomalies(events: list[dict[str, Any]], pos_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = compute_metrics(events, pos_rows)
    heatmap = compute_heatmap(events)
    anomalies: list[dict[str, Any]] = []
    if metrics["current_queue_depth"] >= 6 or metrics["max_queue_depth"] >= 8:
        anomalies.append(
            {
                "type": "QUEUE_SPIKE",
                "severity": "CRITICAL" if metrics["max_queue_depth"] >= 10 else "WARN",
                "suggested_action": "Open another billing counter or move a staff member to checkout.",
                "observed_value": metrics["max_queue_depth"],
            }
        )
    if metrics["unique_visitors"] >= 5 and metrics["conversion_rate"] < 0.15:
        anomalies.append(
            {
                "type": "CONVERSION_DROP",
                "severity": "WARN",
                "suggested_action": "Check staff availability near high-intent zones and verify POS queue friction.",
                "observed_value": metrics["conversion_rate"],
            }
        )
    visited = {zone["zone_id"] for zone in heatmap["zones"] if zone["visits"] > 0}
    for zone in {"SKINCARE", "MAKEUP", "BATH_BODY", "BILLING"} - visited:
        anomalies.append(
            {
                "type": "DEAD_ZONE",
                "severity": "INFO",
                "zone_id": zone,
                "suggested_action": f"Review camera coverage and merchandising for {zone}.",
                "observed_value": 0,
            }
        )
    if not anomalies:
        anomalies.append(
            {
                "type": "NORMAL",
                "severity": "INFO",
                "suggested_action": "No operational action required.",
                "observed_value": None,
            }
        )
    return anomalies


def health(last_by_store: dict[str, str]) -> dict[str, Any]:
    now = datetime.now(UTC)
    stores = {}
    status = "OK"
    for store_id, last_ts in last_by_store.items():
        age_seconds = (now - parse_ts(last_ts)).total_seconds()
        stale = age_seconds > 600
        if stale:
            status = "WARN"
        stores[store_id] = {
            "last_event_timestamp": last_ts,
            "feed_age_seconds": round(age_seconds, 2),
            "warning": "STALE_FEED" if stale else None,
        }
    return {"status": status, "stores": stores}
