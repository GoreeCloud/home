from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re

from .availability import DeviceAvailability, normalize_availability, normalize_reason

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _validate_identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _validate_name(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > 256:
        raise ValueError(f"{label} must be 256 characters or fewer")
    return normalized


def validate_capability(value: str) -> str:
    if not _CAPABILITY.fullmatch(value):
        raise ValueError(f"invalid capability: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class Home:
    id: str
    name: str

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "home id")
        object.__setattr__(self, "name", _validate_name(self.name, "home name"))


@dataclass(frozen=True, slots=True)
class Room:
    id: str
    home_id: str
    name: str

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "room id")
        _validate_identifier(self.home_id, "home id")
        object.__setattr__(self, "name", _validate_name(self.name, "room name"))


@dataclass(slots=True)
class Device:
    id: str
    home_id: str
    name: str
    capabilities: frozenset[str]
    room_id: str | None = None
    adapter: str | None = None
    desired_state: dict[str, Any] = field(default_factory=dict)
    reported_state: dict[str, Any] = field(default_factory=dict)
    desired_revisions: dict[str, int] = field(default_factory=dict)
    reported_revisions: dict[str, int] = field(default_factory=dict)
    availability: DeviceAvailability = DeviceAvailability.UNKNOWN
    availability_updated_at: str | None = None
    availability_reason: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "device id")
        _validate_identifier(self.home_id, "home id")
        if self.room_id is not None:
            _validate_identifier(self.room_id, "room id")
        if self.adapter is not None:
            _validate_identifier(self.adapter, "adapter id")
        self.name = _validate_name(self.name, "device name")
        normalized = frozenset(validate_capability(item) for item in self.capabilities)
        if not normalized:
            raise ValueError("device must expose at least one capability")
        if len(normalized) > 128:
            raise ValueError("device may expose at most 128 capabilities")
        self.capabilities = normalized
        for revisions in (self.desired_revisions, self.reported_revisions):
            for capability, revision in revisions.items():
                validate_capability(capability)
                if type(revision) is not int or revision < 1:
                    raise ValueError("state revisions must be positive integers")
        self.availability = normalize_availability(self.availability)
        self.availability_reason = normalize_reason(self.availability_reason)

    def require_capability(self, capability: str) -> None:
        validate_capability(capability)
        if capability not in self.capabilities:
            raise ValueError(f"device {self.id!r} does not expose {capability!r}")
