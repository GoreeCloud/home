from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping
import re

from .availability import DeviceAvailability, normalize_availability
from .models import validate_capability

AUTOMATION_CONTRACT_VERSION = "1.0"
MAX_SCENE_ACTIONS = 32
MAX_AUTOMATION_ACTIONS = 32
MAX_AUTOMATION_CONDITIONS = 16
MAX_AUTOMATION_RUNS_PER_TRIGGER = 32
MAX_AUTOMATION_RETRY_ATTEMPTS = 3

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_NAME_LIMIT = 256


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _name(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > _NAME_LIMIT:
        raise ValueError(f"{label} must be {_NAME_LIMIT} characters or fewer")
    return normalized


def _json_value(value: Any) -> Any:
    # Deep JSON compatibility validation without accepting NaN/Infinity later in persistence.
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("automation values must be finite JSON values")
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("automation object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    raise ValueError(f"automation value is not JSON-compatible: {type(value).__name__}")


class TriggerKind(str, Enum):
    MANUAL = "manual"
    REPORTED_STATE_EQUALS = "reported_state_equals"
    AVAILABILITY_EQUALS = "availability_equals"
    SCHEDULE = "schedule"


class ConditionKind(str, Enum):
    DESIRED_STATE_EQUALS = "desired_state_equals"
    REPORTED_STATE_EQUALS = "reported_state_equals"
    AVAILABILITY_EQUALS = "availability_equals"


class ActionKind(str, Enum):
    SET_DESIRED = "set_desired"
    ACTIVATE_SCENE = "activate_scene"


class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class SceneAction:
    device_id: str
    capability: str
    value: Any

    def __post_init__(self) -> None:
        _identifier(self.device_id, "device id")
        validate_capability(self.capability)
        object.__setattr__(self, "value", _json_value(self.value))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": ActionKind.SET_DESIRED.value,
            "device_id": self.device_id,
            "capability": self.capability,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SceneAction":
        if value.get("kind") != ActionKind.SET_DESIRED.value:
            raise ValueError("scene actions must use set_desired")
        return cls(
            device_id=str(value["device_id"]),
            capability=str(value["capability"]),
            value=value.get("value"),
        )


@dataclass(frozen=True, slots=True)
class Scene:
    id: str
    home_id: str
    name: str
    actions: tuple[SceneAction, ...]

    def __post_init__(self) -> None:
        _identifier(self.id, "scene id")
        _identifier(self.home_id, "home id")
        object.__setattr__(self, "name", _name(self.name, "scene name"))
        normalized = tuple(self.actions)
        if not normalized:
            raise ValueError("scene must contain at least one action")
        if len(normalized) > MAX_SCENE_ACTIONS:
            raise ValueError(f"scene may contain at most {MAX_SCENE_ACTIONS} actions")
        object.__setattr__(self, "actions", normalized)


@dataclass(frozen=True, slots=True)
class AutomationTrigger:
    kind: TriggerKind
    device_id: str | None = None
    capability: str | None = None
    value: Any = None
    availability: DeviceAvailability | None = None
    schedule_id: str | None = None

    def __post_init__(self) -> None:
        kind = TriggerKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind == TriggerKind.MANUAL:
            if any(
                item is not None
                for item in (self.device_id, self.capability, self.availability, self.schedule_id)
            ) or self.value is not None:
                raise ValueError("manual trigger does not accept selector fields")
            return
        if kind == TriggerKind.REPORTED_STATE_EQUALS:
            if self.device_id is None or self.capability is None:
                raise ValueError("reported-state trigger requires device_id and capability")
            _identifier(self.device_id, "device id")
            validate_capability(self.capability)
            object.__setattr__(self, "value", _json_value(self.value))
            if self.availability is not None or self.schedule_id is not None:
                raise ValueError("reported-state trigger has incompatible selector fields")
            return
        if kind == TriggerKind.AVAILABILITY_EQUALS:
            if self.device_id is None or self.availability is None:
                raise ValueError("availability trigger requires device_id and availability")
            _identifier(self.device_id, "device id")
            object.__setattr__(self, "availability", normalize_availability(self.availability))
            if self.capability is not None or self.schedule_id is not None or self.value is not None:
                raise ValueError("availability trigger has incompatible selector fields")
            return
        if kind == TriggerKind.SCHEDULE:
            if self.schedule_id is None:
                raise ValueError("schedule trigger requires schedule_id")
            _identifier(self.schedule_id, "schedule id")
            if any(
                item is not None
                for item in (self.device_id, self.capability, self.availability)
            ) or self.value is not None:
                raise ValueError("schedule trigger has incompatible selector fields")
            return
        raise ValueError(f"unsupported trigger kind: {kind}")

    @classmethod
    def manual(cls) -> "AutomationTrigger":
        return cls(TriggerKind.MANUAL)

    @classmethod
    def reported_state_equals(
        cls, device_id: str, capability: str, value: Any
    ) -> "AutomationTrigger":
        return cls(
            TriggerKind.REPORTED_STATE_EQUALS,
            device_id=device_id,
            capability=capability,
            value=value,
        )

    @classmethod
    def availability_equals(
        cls, device_id: str, availability: DeviceAvailability | str
    ) -> "AutomationTrigger":
        return cls(
            TriggerKind.AVAILABILITY_EQUALS,
            device_id=device_id,
            availability=normalize_availability(availability),
        )

    @classmethod
    def schedule(cls, schedule_id: str) -> "AutomationTrigger":
        return cls(TriggerKind.SCHEDULE, schedule_id=schedule_id)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind.value}
        if self.device_id is not None:
            result["device_id"] = self.device_id
        if self.capability is not None:
            result["capability"] = self.capability
        if self.kind == TriggerKind.REPORTED_STATE_EQUALS:
            result["value"] = self.value
        if self.availability is not None:
            result["availability"] = self.availability.value
        if self.schedule_id is not None:
            result["schedule_id"] = self.schedule_id
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AutomationTrigger":
        availability = value.get("availability")
        return cls(
            kind=TriggerKind(str(value["kind"])),
            device_id=str(value["device_id"]) if value.get("device_id") is not None else None,
            capability=str(value["capability"]) if value.get("capability") is not None else None,
            value=value.get("value"),
            availability=(
                normalize_availability(str(availability)) if availability is not None else None
            ),
            schedule_id=(
                str(value["schedule_id"]) if value.get("schedule_id") is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class AutomationCondition:
    kind: ConditionKind
    device_id: str
    capability: str | None = None
    value: Any = None
    availability: DeviceAvailability | None = None

    def __post_init__(self) -> None:
        kind = ConditionKind(self.kind)
        object.__setattr__(self, "kind", kind)
        _identifier(self.device_id, "device id")
        if kind in {ConditionKind.DESIRED_STATE_EQUALS, ConditionKind.REPORTED_STATE_EQUALS}:
            if self.capability is None:
                raise ValueError("state condition requires capability")
            validate_capability(self.capability)
            object.__setattr__(self, "value", _json_value(self.value))
            if self.availability is not None:
                raise ValueError("state condition does not accept availability")
        elif kind == ConditionKind.AVAILABILITY_EQUALS:
            if self.availability is None:
                raise ValueError("availability condition requires availability")
            object.__setattr__(self, "availability", normalize_availability(self.availability))
            if self.capability is not None or self.value is not None:
                raise ValueError("availability condition has incompatible fields")

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind.value, "device_id": self.device_id}
        if self.capability is not None:
            result["capability"] = self.capability
            result["value"] = self.value
        if self.availability is not None:
            result["availability"] = self.availability.value
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AutomationCondition":
        availability = value.get("availability")
        return cls(
            kind=ConditionKind(str(value["kind"])),
            device_id=str(value["device_id"]),
            capability=str(value["capability"]) if value.get("capability") is not None else None,
            value=value.get("value"),
            availability=(
                normalize_availability(str(availability)) if availability is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class AutomationAction:
    kind: ActionKind
    device_id: str | None = None
    capability: str | None = None
    value: Any = None
    scene_id: str | None = None

    def __post_init__(self) -> None:
        kind = ActionKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind == ActionKind.SET_DESIRED:
            if self.device_id is None or self.capability is None:
                raise ValueError("set_desired action requires device_id and capability")
            _identifier(self.device_id, "device id")
            validate_capability(self.capability)
            object.__setattr__(self, "value", _json_value(self.value))
            if self.scene_id is not None:
                raise ValueError("set_desired action does not accept scene_id")
        elif kind == ActionKind.ACTIVATE_SCENE:
            if self.scene_id is None:
                raise ValueError("activate_scene action requires scene_id")
            _identifier(self.scene_id, "scene id")
            if self.device_id is not None or self.capability is not None or self.value is not None:
                raise ValueError("activate_scene action has incompatible fields")

    @classmethod
    def set_desired(cls, device_id: str, capability: str, value: Any) -> "AutomationAction":
        return cls(ActionKind.SET_DESIRED, device_id=device_id, capability=capability, value=value)

    @classmethod
    def activate_scene(cls, scene_id: str) -> "AutomationAction":
        return cls(ActionKind.ACTIVATE_SCENE, scene_id=scene_id)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind.value}
        if self.kind == ActionKind.SET_DESIRED:
            result.update(
                {
                    "device_id": self.device_id,
                    "capability": self.capability,
                    "value": self.value,
                }
            )
        else:
            result["scene_id"] = self.scene_id
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AutomationAction":
        return cls(
            kind=ActionKind(str(value["kind"])),
            device_id=str(value["device_id"]) if value.get("device_id") is not None else None,
            capability=str(value["capability"]) if value.get("capability") is not None else None,
            value=value.get("value"),
            scene_id=str(value["scene_id"]) if value.get("scene_id") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class Automation:
    id: str
    home_id: str
    name: str
    trigger: AutomationTrigger
    conditions: tuple[AutomationCondition, ...]
    actions: tuple[AutomationAction, ...]
    enabled: bool = True
    max_attempts: int = 1

    def __post_init__(self) -> None:
        _identifier(self.id, "automation id")
        _identifier(self.home_id, "home id")
        object.__setattr__(self, "name", _name(self.name, "automation name"))
        conditions = tuple(self.conditions)
        actions = tuple(self.actions)
        if len(conditions) > MAX_AUTOMATION_CONDITIONS:
            raise ValueError(
                f"automation may contain at most {MAX_AUTOMATION_CONDITIONS} conditions"
            )
        if not actions:
            raise ValueError("automation must contain at least one action")
        if len(actions) > MAX_AUTOMATION_ACTIONS:
            raise ValueError(f"automation may contain at most {MAX_AUTOMATION_ACTIONS} actions")
        if type(self.enabled) is not bool:
            raise ValueError("automation enabled must be boolean")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= MAX_AUTOMATION_RETRY_ATTEMPTS:
            raise ValueError(
                f"automation max_attempts must be between 1 and {MAX_AUTOMATION_RETRY_ATTEMPTS}"
            )
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "actions", actions)


@dataclass(slots=True)
class Schedule:
    id: str
    home_id: str
    name: str
    hour: int
    minute: int
    weekdays: frozenset[int] = field(default_factory=lambda: frozenset(range(7)))
    enabled: bool = True
    last_fired_key: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.id, "schedule id")
        _identifier(self.home_id, "home id")
        self.name = _name(self.name, "schedule name")
        if type(self.hour) is not int or not 0 <= self.hour <= 23:
            raise ValueError("schedule hour must be an integer from 0 to 23")
        if type(self.minute) is not int or not 0 <= self.minute <= 59:
            raise ValueError("schedule minute must be an integer from 0 to 59")
        normalized = frozenset(self.weekdays)
        if not normalized or any(type(day) is not int or not 0 <= day <= 6 for day in normalized):
            raise ValueError("schedule weekdays must contain integers from 0 to 6")
        self.weekdays = normalized
        if type(self.enabled) is not bool:
            raise ValueError("schedule enabled must be boolean")
        if self.last_fired_key is not None and len(self.last_fired_key) > 64:
            raise ValueError("schedule last_fired_key is invalid")

    def is_due(self, at: datetime) -> bool:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("schedule evaluation requires a timezone-aware datetime")
        return (
            self.enabled
            and at.weekday() in self.weekdays
            and at.hour == self.hour
            and at.minute == self.minute
        )

    def occurrence_key(self, at: datetime) -> str:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("schedule evaluation requires a timezone-aware datetime")
        return at.replace(second=0, microsecond=0).isoformat(timespec="minutes")


@dataclass(frozen=True, slots=True)
class AutomationRun:
    id: int
    automation_id: str
    trigger: AutomationTrigger
    started_at: str
    finished_at: str | None
    status: RunStatus
    actions_executed: int
    error: str | None = None


def normalize_run_time(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("run timestamp must be timezone-aware")
    return current.isoformat()


def trigger_matches(definition: AutomationTrigger, actual: AutomationTrigger) -> bool:
    if definition.kind != actual.kind:
        return False
    if definition.kind == TriggerKind.MANUAL:
        return True
    if definition.kind == TriggerKind.REPORTED_STATE_EQUALS:
        return (
            definition.device_id == actual.device_id
            and definition.capability == actual.capability
            and definition.value == actual.value
        )
    if definition.kind == TriggerKind.AVAILABILITY_EQUALS:
        return (
            definition.device_id == actual.device_id
            and definition.availability == actual.availability
        )
    if definition.kind == TriggerKind.SCHEDULE:
        return definition.schedule_id == actual.schedule_id
    return False


def automation_contract() -> dict[str, Any]:
    return {
        "contract": "goreecloud-home-automation",
        "contract_version": AUTOMATION_CONTRACT_VERSION,
        "trigger_kinds": [kind.value for kind in TriggerKind],
        "condition_kinds": [kind.value for kind in ConditionKind],
        "action_kinds": [kind.value for kind in ActionKind],
        "run_statuses": [status.value for status in RunStatus],
        "limits": {
            "scene_actions": MAX_SCENE_ACTIONS,
            "automation_actions": MAX_AUTOMATION_ACTIONS,
            "automation_conditions": MAX_AUTOMATION_CONDITIONS,
            "automation_runs_per_trigger": MAX_AUTOMATION_RUNS_PER_TRIGGER,
            "automation_retry_attempts": MAX_AUTOMATION_RETRY_ATTEMPTS,
        },
        "schedule": {
            "weekday_domain": [0, 1, 2, 3, 4, 5, 6],
            "requires_timezone_aware_evaluation": True,
            "duplicate_occurrence_suppression": True,
            "background_clock_driver": False,
        },
        "execution": {
            "definition_order": True,
            "all_actions_atomic": True,
            "failed_run_records_error": True,
            "arbitrary_code_actions": False,
            "network_write_api_exposed": False,
        },
    }
