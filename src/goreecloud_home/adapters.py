from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .models import _validate_identifier

ADAPTER_CONTRACT_VERSION = "1.0"


class AdapterLifecycle(str, Enum):
    REGISTERED = "registered"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPED = "stopped"


_ALLOWED_TRANSITIONS: dict[AdapterLifecycle, frozenset[AdapterLifecycle]] = {
    AdapterLifecycle.REGISTERED: frozenset({AdapterLifecycle.STARTING, AdapterLifecycle.STOPPED}),
    AdapterLifecycle.STARTING: frozenset({AdapterLifecycle.READY, AdapterLifecycle.DEGRADED, AdapterLifecycle.FAILED, AdapterLifecycle.STOPPED}),
    AdapterLifecycle.READY: frozenset({AdapterLifecycle.DEGRADED, AdapterLifecycle.FAILED, AdapterLifecycle.STOPPED}),
    AdapterLifecycle.DEGRADED: frozenset({AdapterLifecycle.READY, AdapterLifecycle.FAILED, AdapterLifecycle.STOPPED}),
    AdapterLifecycle.FAILED: frozenset({AdapterLifecycle.STARTING, AdapterLifecycle.STOPPED}),
    AdapterLifecycle.STOPPED: frozenset({AdapterLifecycle.STARTING}),
}


def normalize_adapter_lifecycle(value: AdapterLifecycle | str) -> AdapterLifecycle:
    if isinstance(value, AdapterLifecycle):
        return value
    return AdapterLifecycle(value)


def validate_adapter_transition(current: AdapterLifecycle, target: AdapterLifecycle) -> None:
    if current == target:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid adapter lifecycle transition: {current.value} -> {target.value}")


def normalize_adapter_observed_at(value: datetime | None = None) -> str:
    observed = value or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("adapter observation time must be timezone-aware")
    return observed.astimezone(timezone.utc).isoformat()


def normalize_adapter_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    normalized = reason.strip()
    if not normalized:
        return None
    if len(normalized) > 512:
        raise ValueError("adapter lifecycle reason must be 512 characters or fewer")
    return normalized


@dataclass(slots=True)
class AdapterRecord:
    id: str
    protocol: str
    lifecycle: AdapterLifecycle = AdapterLifecycle.REGISTERED
    updated_at: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "adapter id")
        _validate_identifier(self.protocol, "adapter protocol")
        self.lifecycle = normalize_adapter_lifecycle(self.lifecycle)
        self.reason = normalize_adapter_reason(self.reason)


def adapter_contract() -> dict[str, object]:
    return {
        "contract": "goreecloud-home-adapter-lifecycle",
        "contract_version": ADAPTER_CONTRACT_VERSION,
        "states": [item.value for item in AdapterLifecycle],
        "initial_state": AdapterLifecycle.REGISTERED.value,
        "same_state_observation": True,
        "allowed_transitions": {
            source.value: sorted(target.value for target in targets)
            for source, targets in _ALLOWED_TRANSITIONS.items()
        },
        "device_reference_requires_registration": True,
    }
