from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib import request


def post(api: str, event: dict) -> None:
    payload = json.dumps({"events": [event]}).encode("utf-8")
    req = request.Request(
        f"{api.rstrip('/')}/events/ingest",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    request.urlopen(req, timeout=10).read()


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay events into the API as a simulated live stream.")
    parser.add_argument("--events", default=Path("data/generated_events.jsonl"), type=Path)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--sleep", type=float, default=0.25)
    args = parser.parse_args()
    for line in args.events.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        post(args.api, json.loads(line))
        print(".", end="", flush=True)
        time.sleep(args.sleep)
    print("\nLive replay complete")


if __name__ == "__main__":
    main()
