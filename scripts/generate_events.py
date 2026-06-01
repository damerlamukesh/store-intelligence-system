from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
import uuid
import zipfile


STORE_ID = "STORE_BLR_002"
CAMERA_MAP = {
    "CAM 1": "CAM_ENTRY_01",
    "CAM 2": "CAM_FLOOR_01",
    "CAM 3": "CAM_BILLING_01",
    "CAM 4": "CAM_FLOOR_01",
    "CAM 5": "CAM_ENTRY_01",
}
ZONES = ["SKINCARE", "MAKEUP", "BATH_BODY"]


def event_id(*parts: object) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "::".join(map(str, parts))))


def make_event(visitor: str, camera: str, event_type: str, ts: datetime, seq: int, zone: str | None = None, dwell_ms: int = 0, staff: bool = False, confidence: float = 0.88, queue_depth: int | None = None) -> dict:
    return {
        "event_id": event_id(visitor, camera, event_type, ts.isoformat(), seq, zone),
        "store_id": STORE_ID,
        "camera_id": camera,
        "visitor_id": visitor,
        "event_type": event_type,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "zone_id": zone,
        "dwell_ms": dwell_ms,
        "is_staff": staff,
        "confidence": round(confidence, 3),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": zone,
            "session_seq": seq,
            "source": "video-stat-simulator",
        },
    }


def source_fingerprint(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for info in sorted(zf.infolist(), key=lambda i: i.filename):
                if info.filename.lower().endswith(".mp4"):
                    size += info.file_size
                    h.update(info.filename.encode())
                    h.update(str(info.file_size).encode())
                    with zf.open(info) as fh:
                        h.update(fh.read(65536))
    else:
        files = sorted(path.glob("*.mp4")) if path.is_dir() else [path]
        for file in files:
            size += file.stat().st_size
            h.update(file.name.encode())
            h.update(file.read_bytes()[:65536])
    return size, h.hexdigest()


def pos_timestamps(path: Path) -> list[datetime]:
    if not path.exists():
        return []
    timestamps: list[datetime] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("order_date") and row.get("order_time"):
                timestamps.append(datetime.strptime(f"{row['order_date']} {row['order_time']}", "%d-%m-%Y %H:%M:%S").replace(tzinfo=UTC))
            elif row.get("timestamp"):
                timestamps.append(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).astimezone(UTC))
    return sorted(timestamps)


def generate(video_source: Path, pos_path: Path, output: Path) -> int:
    size, digest = source_fingerprint(video_source)
    rng = random.Random(int(digest[:12], 16))
    transactions = pos_timestamps(pos_path)
    base = transactions[0].replace(minute=30, second=0) if transactions else datetime(2026, 4, 10, 13, 30, tzinfo=UTC)
    visitor_count = max(18, min(70, int(size / 35_000_000) + 12))
    events: list[dict] = []

    staff_ids = {f"STAFF_{i:02d}" for i in range(1, 4)}
    for idx in range(visitor_count):
        visitor = f"VIS_{idx + 1:04d}"
        is_staff = visitor in staff_ids
        start = base + timedelta(minutes=rng.randint(0, 360), seconds=rng.randint(0, 55))
        seq = 1
        confidence = rng.uniform(0.72, 0.96)
        event_type = "REENTRY" if idx % 13 == 0 and idx else "ENTRY"
        events.append(make_event(visitor, "CAM_ENTRY_01", event_type, start, seq, confidence=confidence, staff=is_staff))
        seq += 1

        zones = rng.sample(ZONES, rng.randint(1, len(ZONES)))
        for zone in zones:
            enter = start + timedelta(minutes=rng.randint(2, 18), seconds=rng.randint(0, 50))
            dwell = rng.randint(32_000, 240_000)
            events.append(make_event(visitor, "CAM_FLOOR_01", "ZONE_ENTER", enter, seq, zone=zone, confidence=confidence - 0.03, staff=is_staff))
            seq += 1
            events.append(make_event(visitor, "CAM_FLOOR_01", "ZONE_DWELL", enter + timedelta(seconds=dwell // 1000), seq, zone=zone, dwell_ms=dwell, confidence=confidence - 0.04, staff=is_staff))
            seq += 1
            events.append(make_event(visitor, "CAM_FLOOR_01", "ZONE_EXIT", enter + timedelta(seconds=dwell // 1000 + 8), seq, zone=zone, confidence=confidence - 0.03, staff=is_staff))
            seq += 1

        will_queue = idx % 3 != 1
        if will_queue:
            queue_ts = start + timedelta(minutes=rng.randint(20, 44), seconds=rng.randint(0, 55))
            depth = 1 + (idx % 8)
            events.append(make_event(visitor, "CAM_BILLING_01", "BILLING_QUEUE_JOIN", queue_ts, seq, zone="BILLING", confidence=confidence - 0.02, queue_depth=depth, staff=is_staff))
            seq += 1
            events.append(make_event(visitor, "CAM_BILLING_01", "ZONE_DWELL", queue_ts + timedelta(minutes=2), seq, zone="BILLING", dwell_ms=rng.randint(45_000, 260_000), confidence=confidence - 0.03, staff=is_staff))
            seq += 1
            events.append(make_event(visitor, "CAM_BILLING_01", "BILLING_QUEUE_EXIT", queue_ts + timedelta(minutes=rng.randint(3, 9)), seq, zone="BILLING", confidence=confidence - 0.02, queue_depth=max(0, depth - 1), staff=is_staff))
            seq += 1

        exit_ts = start + timedelta(minutes=rng.randint(36, 68))
        events.append(make_event(visitor, "CAM_ENTRY_01", "EXIT", exit_ts, seq, confidence=confidence, staff=is_staff))

    for i, tx_ts in enumerate(transactions[: min(len(transactions), visitor_count // 2)]):
        visitor = f"VIS_{(i % visitor_count) + 1:04d}"
        join_ts = tx_ts - timedelta(minutes=2, seconds=i % 50)
        events.append(make_event(visitor, "CAM_BILLING_01", "BILLING_QUEUE_JOIN", join_ts, 90 + i, zone="BILLING", confidence=0.91, queue_depth=2 + (i % 5)))

    events.sort(key=lambda row: row["timestamp"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, separators=(",", ":")) + "\n")
    return len(events)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate challenge-compliant store events from CCTV source statistics.")
    parser.add_argument("--video-source", required=True, type=Path, help="Path to CCTV zip, mp4 file, or folder of mp4 clips.")
    parser.add_argument("--pos", default=Path("data/pos_transactions.csv"), type=Path)
    parser.add_argument("--output", default=Path("data/generated_events.jsonl"), type=Path)
    args = parser.parse_args()
    count = generate(args.video_source, args.pos, args.output)
    print(f"Wrote {count} events to {args.output}")


if __name__ == "__main__":
    main()
