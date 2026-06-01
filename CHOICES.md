# CHOICES.md

## 1. Detection Model Choice

Options considered: YOLOv8 + ByteTrack, RT-DETR, OpenCV background subtraction, and a deterministic simulator.

AI suggestion: use YOLOv8 for people detection and ByteTrack for identity continuity, with a lightweight fallback for reviewers without GPU support.

Choice: I implemented the fallback adapter as the submitted runnable path and documented the YOLOv8 + ByteTrack production path. The challenge rewards a working system, and reviewers must be able to run it quickly with Docker. The event boundary means a stronger model can replace the generator without touching the API.

## 2. Event Schema Design

Options considered: one table per event type, a single generic event table, or raw frame detections plus derived analytics tables.

AI suggestion: keep a single append-only event table and place model-specific details in `metadata`.

Choice: I used a single event contract matching the problem statement. This keeps ingest idempotent, makes replay easy, and supports held-out scoring tests that post their own events.

## 3. API Architecture Choice

Options considered: in-memory store, PostgreSQL, Kafka plus stream processor, or SQLite-backed FastAPI.

AI suggestion: use FastAPI and SQLite for the challenge, while keeping interfaces close to a production service.

Choice: I chose FastAPI + SQLite. It runs with one container, needs no external database setup, supports SQL queries and idempotency, and is enough for reviewer-scale traffic. For production I would move storage to PostgreSQL and put Kafka or Redpanda between detection workers and the API.
