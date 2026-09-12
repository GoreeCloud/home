from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from .time_semantics import CalendarDateWindow

PERSISTED_CALENDAR_CONSTRAINT_VERSION = 1
_REQUIRED_FIELDS = frozenset({"schema_version", "start", "end"})


@dataclass(frozen=True, slots=True)
class PersistedCalendarConstraint:
    """Strict, migration-friendly representation of a local calendar window.

    This contract is intentionally location-free. It can be embedded in persisted
    schedule metadata without creating or discovering household coordinates.
    """

    start: date
    end: date
    schema_version: int = PERSISTED_CALENDAR_CONSTRAINT_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("calendar constraint schema_version must be an integer")
        if self.schema_version != PERSISTED_CALENDAR_CONSTRAINT_VERSION:
            raise ValueError(
                f"unsupported calendar constraint schema_version: {self.schema_version}"
            )
        CalendarDateWindow(self.start, self.end)

    @classmethod
    def from_window(cls, window: CalendarDateWindow) -> "PersistedCalendarConstraint":
        return cls(start=window.start, end=window.end)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PersistedCalendarConstraint":
        if not isinstance(value, Mapping):
            raise ValueError("calendar constraint must be an object")
        keys = frozenset(value.keys())
        if keys != _REQUIRED_FIELDS:
            missing = sorted(_REQUIRED_FIELDS - keys)
            unknown = sorted(keys - _REQUIRED_FIELDS)
            details: list[str] = []
            if missing:
                details.append(f"missing fields: {', '.join(missing)}")
            if unknown:
                details.append(f"unknown fields: {', '.join(unknown)}")
            raise ValueError("invalid calendar constraint object; " + "; ".join(details))

        version = value["schema_version"]
        if type(version) is not int:
            raise ValueError("calendar constraint schema_version must be an integer")
        start = _parse_date(value["start"], "start")
        end = _parse_date(value["end"], "end")
        return cls(start=start, end=end, schema_version=version)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }

    def as_window(self) -> CalendarDateWindow:
        return CalendarDateWindow(self.start, self.end)

    def allows(self, at: datetime) -> bool:
        return self.as_window().contains(at)


def _parse_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"calendar constraint {label} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"calendar constraint {label} must be an ISO date string"
        ) from exc
    return parsed
