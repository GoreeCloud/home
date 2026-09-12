from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
import json

from .storage import SQLiteHomeDatabase


@dataclass(frozen=True, slots=True)
class Event:
    sequence: int
    event_type: str
    entity_id: str
    occurred_at: str
    payload: dict[str, Any]


class EventJournal:
    """Durable local event journal for Home Core domain transitions."""

    def __init__(self, path: str | Path | SQLiteHomeDatabase) -> None:
        if isinstance(path, SQLiteHomeDatabase):
            self.database = path
            self._owns_database = False
        else:
            self.database = SQLiteHomeDatabase(path)
            self._owns_database = True

    def close(self) -> None:
        if self._owns_database:
            self.database.close()

    def transaction(self) -> Iterator[SQLiteHomeDatabase]:
        return self.database.transaction()

    def append(self, event_type: str, entity_id: str, payload: dict[str, Any]) -> Event:
        if not event_type or not entity_id:
            raise ValueError("event_type and entity_id are required")
        occurred_at = datetime.now(timezone.utc).isoformat()
        encoded = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        sequence = self.database.insert(
            "INSERT INTO events(event_type, entity_id, occurred_at, payload_json) VALUES (?, ?, ?, ?)",
            (event_type, entity_id, occurred_at, encoded),
        )
        return Event(sequence, event_type, entity_id, occurred_at, json.loads(encoded))

    def list_since(self, sequence: int = 0, limit: int = 100) -> list[Event]:
        if sequence < 0:
            raise ValueError("sequence must be non-negative")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        rows = self.database.fetchall(
            "SELECT sequence, event_type, entity_id, occurred_at, payload_json "
            "FROM events WHERE sequence > ? ORDER BY sequence ASC LIMIT ?",
            (sequence, limit),
        )
        return [
            Event(
                sequence=int(row["sequence"]),
                event_type=str(row["event_type"]),
                entity_id=str(row["entity_id"]),
                occurred_at=str(row["occurred_at"]),
                payload=json.loads(str(row["payload_json"])),
            )
            for row in rows
        ]

    def ready(self) -> bool:
        return self.database.ready()
