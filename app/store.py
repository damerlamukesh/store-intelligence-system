from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .models import StoreEvent


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  store_id TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  visitor_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  zone_id TEXT,
  dwell_ms INTEGER NOT NULL,
  is_staff INTEGER NOT NULL,
  confidence REAL NOT NULL,
  metadata TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_store_time ON events(store_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(store_id, visitor_id);
CREATE TABLE IF NOT EXISTS pos_transactions (
  transaction_id TEXT PRIMARY KEY,
  store_id TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  basket_value_inr REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pos_store_time ON pos_transactions(store_id, timestamp);
"""


class EventStore:
    def __init__(self, db_path: Path, pos_path: Path | None = None) -> None:
        self.db_path = db_path
        self.pos_path = pos_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
        if self.pos_path and self.pos_path.exists():
            self.load_pos(self.pos_path)

    def load_pos(self, path: Path) -> None:
        with path.open("r", encoding="utf-8-sig", newline="") as fh, self.connect() as conn:
            reader = csv.DictReader(fh)
            for row in reader:
                tx_id = row.get("transaction_id") or row.get("invoice_number") or row.get("order_id")
                store_id = row.get("store_id") or "STORE_BLR_002"
                if row.get("store_name") == "Brigade_Bangalore" or store_id == "ST1008":
                    store_id = "STORE_BLR_002"
                raw_date = row.get("order_date")
                raw_time = row.get("order_time")
                timestamp = row.get("timestamp")
                if raw_date and raw_time:
                    timestamp = datetime.strptime(f"{raw_date} {raw_time}", "%d-%m-%Y %H:%M:%S").replace(tzinfo=UTC).isoformat()
                amount = row.get("basket_value_inr") or row.get("NMV") or row.get("GMV") or 0
                if tx_id and timestamp:
                    conn.execute(
                        "INSERT OR IGNORE INTO pos_transactions VALUES (?, ?, ?, ?)",
                        (str(tx_id), store_id, timestamp, float(amount)),
                    )

    def ingest(self, events: list[StoreEvent]) -> tuple[int, int]:
        accepted = duplicate = 0
        with self.connect() as conn:
            for event in events:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.store_id,
                        event.camera_id,
                        event.visitor_id,
                        event.event_type.value,
                        event.timestamp.astimezone(UTC).isoformat(),
                        event.zone_id,
                        event.dwell_ms,
                        int(event.is_staff),
                        event.confidence,
                        event.metadata.model_dump_json(),
                    ),
                )
                if cur.rowcount:
                    accepted += 1
                else:
                    duplicate += 1
        return accepted, duplicate

    def events(self, store_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE store_id = ? ORDER BY timestamp, visitor_id",
                (store_id,),
            ).fetchall()
        return [dict(row) | {"metadata": json.loads(row["metadata"])} for row in rows]

    def pos(self, store_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pos_transactions WHERE store_id = ? ORDER BY timestamp",
                (store_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def last_event_by_store(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT store_id, MAX(timestamp) AS last_ts FROM events GROUP BY store_id"
            ).fetchall()
        return {row["store_id"]: row["last_ts"] for row in rows}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def correlate_purchases(events: list[dict[str, Any]], pos_rows: list[dict[str, Any]]) -> set[str]:
    billing_visits = [
        (row["visitor_id"], parse_ts(row["timestamp"]))
        for row in events
        if row["event_type"] in {"BILLING_QUEUE_JOIN", "ZONE_DWELL", "ZONE_ENTER"}
        and row["zone_id"] == "BILLING"
        and not row["is_staff"]
    ]
    converted: set[str] = set()
    for tx in pos_rows:
        tx_ts = parse_ts(tx["timestamp"])
        window_start = tx_ts - timedelta(minutes=5)
        for visitor_id, event_ts in billing_visits:
            if window_start <= event_ts <= tx_ts:
                converted.add(visitor_id)
                break
    return converted
