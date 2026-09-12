from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
import re

from .automation import Schedule
from .persisted_calendar import PersistedCalendarConstraint

PERSISTED_SCHEDULE_CALENDAR_BINDING_VERSION = 1
_REQUIRED_FIELDS = frozenset({"schema_version", "schedule_id", "calendar"})
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class PersistedScheduleCalendarBinding:
    """Migration-safe calendar constraint bound to one existing schedule.

    The binding intentionally carries no location, coordinates, geofence, or
    solar data. It is a small persistable bridge between the existing Schedule
    contract and the separately versioned calendar-window contract.
    """

    schedule_id: str
    calendar: PersistedCalendarConstraint
    schema_version: int = PERSISTED_SCHEDULE_CALENDAR_BINDING_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("schedule calendar binding schema_version must be an integer")
        if self.schema_version != PERSISTED_SCHEDULE_CALENDAR_BINDING_VERSION:
            raise ValueError(
                f"unsupported schedule calendar binding schema_version: {self.schema_version}"
            )
        if not isinstance(self.schedule_id, str) or not _IDENTIFIER.fullmatch(self.schedule_id):
            raise ValueError("schedule calendar binding schedule_id is invalid")
        if not isinstance(self.calendar, PersistedCalendarConstraint):
            raise ValueError("schedule calendar binding calendar is invalid")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PersistedScheduleCalendarBinding":
        if not isinstance(value, Mapping):
            raise ValueError("schedule calendar binding must be an object")
        keys = frozenset(value.keys())
        if keys != _REQUIRED_FIELDS:
            missing = sorted(_REQUIRED_FIELDS - keys)
            unknown = sorted(keys - _REQUIRED_FIELDS)
            details: list[str] = []
            if missing:
                details.append(f"missing fields: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown fields: {', '.join(unknown)}")
            raise ValueError("invalid schedule calendar binding object; " + "; ".join(details))

        version = value["schema_version"]
        if type(version) is not int:
            raise ValueError("schedule calendar binding schema_version must be an integer")
        schedule_id = value["schedule_id"]
        if not isinstance(schedule_id, str):
            raise ValueError("schedule calendar binding schedule_id must be a string")
        calendar = value["calendar"]
        if not isinstance(calendar, Mapping):
            raise ValueError("schedule calendar binding calendar must be an object")
        return cls(
            schedule_id=schedule_id,
            calendar=PersistedCalendarConstraint.from_dict(calendar),
            schema_version=version,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "schedule_id": self.schedule_id,
            "calendar": self.calendar.as_dict(),
        }

    def is_due(self, schedule: Schedule, at: datetime) -> bool:
        self._require_matching_schedule(schedule)
        return self.calendar.allows(at) and schedule.is_due(at)

    def occurrence_key(self, schedule: Schedule, at: datetime) -> str | None:
        if not self.is_due(schedule, at):
            return None
        return schedule.occurrence_key(at)

    def unfired_occurrence_key(self, schedule: Schedule, at: datetime) -> str | None:
        """Return the due occurrence only when the schedule has not recorded it.

        ``Schedule.last_fired_key`` is already the automation engine's durable
        duplicate-occurrence checkpoint. Reusing that authority keeps calendar
        constraints from creating a second deduplication model and makes a
        restarted engine fail closed for an occurrence it has already committed.
        This helper does not mutate the schedule or persist anything by itself.
        """

        key = self.occurrence_key(schedule, at)
        if key is None or schedule.last_fired_key == key:
            return None
        return key

    def _require_matching_schedule(self, schedule: Schedule) -> None:
        if not isinstance(schedule, Schedule):
            raise ValueError("schedule calendar binding requires a Schedule")
        if schedule.id != self.schedule_id:
            raise ValueError("schedule calendar binding does not match schedule id")
