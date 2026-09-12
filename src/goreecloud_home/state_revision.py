from __future__ import annotations

STATE_REVISION_CONTRACT_VERSION = "1.0"
INITIAL_STATE_REVISION = 1
CREATE_EXPECTED_REVISION = 0


class StateConflictError(RuntimeError):
    """Raised when an optimistic state mutation targets a stale revision."""

    code = "state_revision_conflict"

    def __init__(
        self,
        *,
        device_id: str,
        state_kind: str,
        capability: str,
        expected_revision: int,
        actual_revision: int,
    ) -> None:
        self.device_id = device_id
        self.state_kind = state_kind
        self.capability = capability
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f"state revision conflict for {device_id}/{state_kind}/{capability}: "
            f"expected {expected_revision}, actual {actual_revision}"
        )


def validate_expected_revision(value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("expected_revision must be a non-negative integer or None")
    return value


def state_revision_contract() -> dict[str, object]:
    return {
        "contract": "goreecloud-home-state-revision",
        "contract_version": STATE_REVISION_CONTRACT_VERSION,
        "state_kinds": ["desired", "reported"],
        "initial_revision": INITIAL_STATE_REVISION,
        "create_expected_revision": CREATE_EXPECTED_REVISION,
        "mutation_increment": 1,
        "unconditional_expected_revision": None,
        "conflict_error": StateConflictError.code,
    }
