from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib import request


def batches(rows: list[dict], size: int = 500):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def main() -> None:
    parser = argparse.ArgumentParser(description="Feed JSONL events into the Store Intelligence API.")
    parser.add_argument("--events", default=Path("data/generated_events.jsonl"), type=Path)
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.events.read_text(encoding="utf-8").splitlines() if line.strip()]
    accepted = duplicate = failed = 0
    for batch in batches(rows):
        payload = json.dumps({"events": batch}).encode("utf-8")
        req = request.Request(
            f"{args.api.rstrip('/')}/events/ingest",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            accepted += body["accepted"]
            duplicate += body["duplicate"]
            failed += body["failed"]
    print(json.dumps({"accepted": accepted, "duplicate": duplicate, "failed": failed}, indent=2))


if __name__ == "__main__":
    main()
