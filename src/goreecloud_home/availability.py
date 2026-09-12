from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class DeviceAvailability(str, Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


_ALLOWED_TRANSITIONS: dict[DeviceAvailability, frozenset[DeviceAvailability]] = {
    DeviceAvailability.UNKNOWN: frozenset(
        {
            DeviceAvailability.ONLINE,
            DeviceAvailability.DEGRADED,
            DeviceAvailability.OFFLINE,
        }
    ),
    DeviceAvailability.ONLINE: frozenset(
        {DeviceAvailability.DEGRADED, DeviceAvailability.OFFLINE}
    ),
    DeviceAvailability.DEGRADED: frozenset(
        {DeviceAvailability.ONLINE, DeviceAvailability.OFFLINE}
    ),
    DeviceAvailability.OFFLINE: frozenset(
        {DeviceAvailability.ONLINE, DeviceAvailability.DEGRADED}
    ),
}


def normalize_availability(value: DeviceAvailability | str) -> DeviceAvailability:
    if isinstance(value, DeviceAvailability):
        return value
    return DeviceAvailability(value)


def validate_availability_transition(
    current: DeviceAvailability,
    target: DeviceAvailability,
) -> None:
    if current == target:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid availability transition: {current.value} -> {target.value}")


def normalize_observed_at(value: datetime | None = None) -> str:
    observed = value or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("availability observation time must be timezone-aware")
    return observed.astimezone(timezone.utc).isoformat()


def normalize_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    normalized = reason.strip()
    if not normalized:
        return None
    if len(normalized) > 512:
        raise ValueError("availability reason must be 512 characters or fewer")
    return normalized


def availability_contract() -> dict[str, object]:
    return {
        "contract": "goreecloud-home-device-availability",
        "contract_version": "1.0",
        "states": [item.value for item in DeviceAvailability],
        "allowed_transitions": {
            source.value: sorted(target.value for target in targets)
            for source, targets in _ALLOWED_TRANSITIONS.items()
        },
        "same_state_observation": True,
        "unknown_is_initial_only": True,
    }
