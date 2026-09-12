from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import math

from .models import validate_capability

CAPABILITY_CONTRACT_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    name: str
    version: int
    value_kind: str
    writable: bool
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: tuple[str, ...] = ()
    desired_allowed_values: tuple[str, ...] = ()
    unit: str | None = None

    def __post_init__(self) -> None:
        validate_capability(self.name)
        if self.version < 1:
            raise ValueError("capability version must be at least 1")
        if self.value_kind not in {"boolean", "integer", "number", "string"}:
            raise ValueError(f"unsupported value kind: {self.value_kind}")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("capability minimum cannot exceed maximum")
        if self.allowed_values and self.value_kind != "string":
            raise ValueError("allowed_values are supported only for string capabilities")
        if len(set(self.allowed_values)) != len(self.allowed_values):
            raise ValueError("allowed_values must be unique")
        if self.desired_allowed_values and self.value_kind != "string":
            raise ValueError("desired_allowed_values are supported only for string capabilities")
        if len(set(self.desired_allowed_values)) != len(self.desired_allowed_values):
            raise ValueError("desired_allowed_values must be unique")
        if self.desired_allowed_values and not set(self.desired_allowed_values).issubset(self.allowed_values):
            raise ValueError("desired_allowed_values must be a subset of allowed_values")

    def validate_value(self, value: Any, *, desired: bool = False) -> None:
        if self.value_kind == "boolean":
            if type(value) is not bool:
                raise ValueError(f"{self.name} requires a boolean")
        elif self.value_kind == "integer":
            if type(value) is not int:
                raise ValueError(f"{self.name} requires an integer")
            self._validate_number(float(value))
        elif self.value_kind == "number":
            if type(value) not in {int, float}:
                raise ValueError(f"{self.name} requires a number")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"{self.name} requires a finite number")
            self._validate_number(number)
        elif self.value_kind == "string":
            if not isinstance(value, str):
                raise ValueError(f"{self.name} requires a string")
            allowed = self.desired_allowed_values if desired and self.desired_allowed_values else self.allowed_values
            if allowed and value not in allowed:
                raise ValueError(f"{self.name} must be one of {', '.join(allowed)}")

    def _validate_number(self, value: float) -> None:
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{self.name} must be >= {self.minimum:g}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{self.name} must be <= {self.maximum:g}")

    def as_contract(self) -> dict[str, object]:
        result: dict[str, object] = {
            "name": self.name,
            "version": self.version,
            "value_kind": self.value_kind,
            "writable": self.writable,
        }
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        if self.allowed_values:
            result["allowed_values"] = list(self.allowed_values)
        if self.desired_allowed_values:
            result["desired_allowed_values"] = list(self.desired_allowed_values)
        if self.unit is not None:
            result["unit"] = self.unit
        return result


class CapabilityRegistry:
    def __init__(self, definitions: Iterable[CapabilityDefinition] = ()) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        for definition in definitions:
            self.register(definition)

    @property
    def contract_version(self) -> str:
        return CAPABILITY_CONTRACT_VERSION

    def register(self, definition: CapabilityDefinition) -> None:
        existing = self._definitions.get(definition.name)
        if existing is not None and existing != definition:
            raise ValueError(f"capability already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def require(self, name: str) -> CapabilityDefinition:
        validate_capability(name)
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ValueError(f"unknown capability contract: {name}") from exc

    def validate_device_capabilities(self, names: Iterable[str]) -> None:
        for name in names:
            self.require(name)

    def validate_desired(self, name: str, value: Any) -> None:
        definition = self.require(name)
        if not definition.writable:
            raise ValueError(f"capability is read-only: {name}")
        definition.validate_value(value, desired=True)

    def validate_reported(self, name: str, value: Any) -> None:
        self.require(name).validate_value(value)

    def as_contract(self) -> dict[str, object]:
        return {
            "contract": "goreecloud-home-capabilities",
            "contract_version": self.contract_version,
            "capabilities": [definition.as_contract() for _, definition in sorted(self._definitions.items())],
        }


BUILTIN_CAPABILITIES = (
    CapabilityDefinition("cover.position", 1, "integer", True, 0, 100, unit="percent"),
    CapabilityDefinition(
        "lock.state",
        1,
        "string",
        True,
        allowed_values=("locked", "unlocked", "jammed", "unknown"),
        desired_allowed_values=("locked", "unlocked"),
    ),
    CapabilityDefinition("light.brightness", 1, "integer", True, 0, 100, unit="percent"),
    CapabilityDefinition("light.power", 1, "boolean", True),
    CapabilityDefinition("sensor.contact", 1, "string", False, allowed_values=("open", "closed")),
    CapabilityDefinition("sensor.humidity", 1, "number", False, 0, 100, unit="percent"),
    CapabilityDefinition("sensor.motion", 1, "boolean", False),
    CapabilityDefinition("sensor.temperature", 1, "number", False, unit="celsius"),
    CapabilityDefinition("switch.power", 1, "boolean", True),
    CapabilityDefinition("thermostat.target_temperature", 1, "number", True, -50, 80, unit="celsius"),
)


def default_capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry(BUILTIN_CAPABILITIES)
