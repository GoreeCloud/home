from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .adapters import AdapterLifecycle
from .automation import AutomationRun
from .automation_runtime import HomeAutomationRuntime
from .availability import DeviceAvailability
from .core import HomeCore

ADAPTER_EVENT_CONTRACT_VERSION = "1.0"
_ALLOWED_INGRESS_LIFECYCLES = frozenset(
    {AdapterLifecycle.READY.value, AdapterLifecycle.DEGRADED.value}
)


@dataclass(frozen=True, slots=True)
class AdapterDispatchResult:
    state_revision: int | None
    automation_runs: tuple[AutomationRun, ...]


class LocalAdapterEventRouter:
    """Trusted local ingress for future protocol adapters.

    The router does not implement Matter, Thread, Zigbee, Z-Wave, MQTT, BLE, LAN, or
    vendor protocols. It only enforces that a local adapter is registered, in an
    ingress-capable lifecycle state, and bound to the target device before accepting
    reported state or availability observations. Accepted events commit through HomeCore
    and are then drained through the local automation runtime.
    """

    def __init__(self, core: HomeCore, runtime: HomeAutomationRuntime) -> None:
        if runtime.engine.core is not core:
            raise ValueError("adapter event router and automation runtime must share Home Core")
        self.core = core
        self.runtime = runtime

    def report_state(
        self,
        adapter_id: str,
        device_id: str,
        capability: str,
        value: Any,
        *,
        expected_revision: int | None = None,
    ) -> AdapterDispatchResult:
        self._validate_binding(adapter_id, device_id)
        revision = self.core.set_reported_state(
            device_id,
            capability,
            value,
            expected_revision=expected_revision,
        )
        runs = tuple(self.runtime.drain_events())
        return AdapterDispatchResult(revision, runs)

    def observe_availability(
        self,
        adapter_id: str,
        device_id: str,
        availability: DeviceAvailability | str,
        *,
        observed_at: datetime | None = None,
        reason: str | None = None,
    ) -> AdapterDispatchResult:
        self._validate_binding(adapter_id, device_id)
        self.core.observe_device_availability(
            device_id,
            availability,
            observed_at=observed_at,
            reason=reason,
        )
        runs = tuple(self.runtime.drain_events())
        return AdapterDispatchResult(None, runs)

    def _validate_binding(self, adapter_id: str, device_id: str) -> None:
        snapshot = self.core.snapshot()
        adapter = snapshot["adapter_state"].get(adapter_id)
        if adapter is None:
            raise KeyError(f"unknown adapter: {adapter_id}")
        if adapter["lifecycle"] not in _ALLOWED_INGRESS_LIFECYCLES:
            raise RuntimeError(
                f"adapter is not ready for event ingress: {adapter_id} ({adapter['lifecycle']})"
            )
        device = snapshot["device_state"].get(device_id)
        if device is None:
            raise KeyError(f"unknown device: {device_id}")
        if device["adapter"] != adapter_id:
            raise ValueError("device is not bound to the reporting adapter")


def adapter_event_contract() -> dict[str, object]:
    return {
        "contract": "goreecloud-home-adapter-events",
        "contract_version": ADAPTER_EVENT_CONTRACT_VERSION,
        "scope": "trusted-local-ingress",
        "accepted_adapter_lifecycle_states": sorted(_ALLOWED_INGRESS_LIFECYCLES),
        "device_reference_requires_adapter_binding": True,
        "event_kinds": ["reported_state", "availability"],
        "reported_state_uses_capability_contract": True,
        "availability_uses_device_availability_contract": True,
        "automatic_local_automation_routing": True,
        "network_ingress_exposed": False,
        "protocol_implementation": False,
    }
