# GoreeCloud Home — Features

## Implemented in 0.1.0-dev.5

- Durable Home/Room/Device state, desired/reported revisions, availability, adapters and event journal in the versioned Home state store.
- Home state schema remains version 5; the companion automation subsystem uses its own migration ledger through automation schema version 2 in the same SQLite authority.
- Capability, availability, state-revision, adapter-lifecycle, adapter-event, automation and automation-runtime v1 contracts.
- Persistent scenes with ordered validated desired-state actions and atomic activation.
- Persistent declarative automations with manual, reported-state, availability and schedule triggers.
- Desired/reported-state and availability conditions.
- `set_desired` and `activate_scene` actions only; arbitrary code/scripts/templates and recursive automation actions are excluded.
- Persistent schedules with weekdays, hour/minute, timezone-aware evaluation and durable duplicate-occurrence suppression.
- A local background controller-time schedule driver through `HomeAutomationRuntime`.
- Automatic ordered local routing of committed changed reported-state and changed availability events into the bounded automation evaluator.
- Durable automation runtime journal cursor with no historical device-event replay when the runtime schema is first introduced.
- Ordered at-least-once runtime delivery semantics; exact crash-deduplicated delivery is not claimed.
- Trusted local adapter-event ingress with adapter lifecycle and device-binding validation; this is a protocol-neutral boundary, not a device-protocol implementation.
- Deterministic trigger matching and definition-order action execution.
- Persistent run history with running/succeeded/failed/skipped states.
- Atomic rollback on failed multi-action attempts and bounded whole-run retries (maximum 3).
- Hard limits for conditions/actions/runs per trigger to reduce accidental loops or runaway execution.
- Dependency-free deterministic sunrise/sunset calculation from caller-supplied coordinates, including UTC date rollover and explicit no-event behavior for polar dates without a horizon crossing.
- Bounded inclusive calendar-date windows requiring timezone-aware evaluation, valid ordering and a maximum 366-day span.
- Read-only loopback liveness/readiness/status HTTP API with bounded aggregate automation-runtime state.
- Platform Contract v0.2 declaration and automated validation workflow.

## Still planned or blocked

- Persisted sunrise/sunset and bounded calendar trigger integration, migration-safe storage and duplicate-occurrence semantics using the implemented deterministic time primitives.
- Presence/geofence triggers through GoreeCloud Location with explicit Privacy Shield policy and acceptance.
- Exact crash-deduplicated automation delivery for future non-idempotent action families.
- Matter/Thread, LAN, MQTT, Zigbee, Z-Wave and BLE protocol adapters and physical-device interoperability.
- Glaze UI Home client and visual automation editor.
- GoreeCloud Identity, Wardveil Security, Privacy Shield, Everkeep, Manager and Mesh runtime integration/acceptance.
- Secure remote access, notifications, cameras/media, energy, AI/voice, hardware acceptance, RC, Stable and production qualification.
