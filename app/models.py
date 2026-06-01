from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    REENTRY = "REENTRY"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_EXIT = "BILLING_QUEUE_EXIT"
    PURCHASE = "PURCHASE"


class EventMetadata(BaseModel):
    queue_depth: int | None = None
    sku_zone: str | None = None
    session_seq: int = Field(default=1, ge=1)
    source: str | None = None
    raw_track_id: str | None = None


class StoreEvent(BaseModel):
    event_id: str = Field(min_length=8)
    store_id: str = Field(min_length=3)
    camera_id: str = Field(min_length=3)
    visitor_id: str = Field(min_length=3)
    event_type: EventType
    timestamp: datetime
    zone_id: str | None = None
    dwell_ms: int = Field(default=0, ge=0)
    is_staff: bool = False
    confidence: float = Field(ge=0, le=1)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("zone_id")
    @classmethod
    def zone_required_for_zone_events(cls, value: str | None, info: Any) -> str | None:
        event_type = info.data.get("event_type")
        zone_events = {
            EventType.ZONE_ENTER,
            EventType.ZONE_EXIT,
            EventType.ZONE_DWELL,
            EventType.BILLING_QUEUE_JOIN,
            EventType.BILLING_QUEUE_EXIT,
        }
        if event_type in zone_events and not value:
            raise ValueError("zone_id is required for zone and queue events")
        return value


class IngestRequest(BaseModel):
    events: list[StoreEvent] = Field(min_length=1, max_length=500)


class IngestError(BaseModel):
    index: int
    event_id: str | None = None
    error: str


class IngestResponse(BaseModel):
    accepted: int
    duplicate: int
    failed: int
    errors: list[IngestError]


class HealthResponse(BaseModel):
    status: Literal["OK", "WARN"]
    stores: dict[str, dict[str, Any]]
