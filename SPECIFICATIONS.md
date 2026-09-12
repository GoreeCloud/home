# GoreeCloud Home — Specifications

## Current checkpoint

- Product: GoreeCloud Home
- Version: 0.1.0-dev.5
- Lifecycle: Development
- Platform Contract: 0.2
- Conformance: Nonconformant
- Implementation boundary: local Home Core plus bounded companion automation engine/runtime

## Architecture

Home Core owns the local Home/Room/Device domain, protocol-neutral capabilities, desired/reported state, device availability, adapter lifecycle, versioned SQLite state and durable event journal. `HomeAutomationEngine` attaches to the same local SQLite authority/journal and owns scenes, schedules, automation definitions and execution history. `HomeAutomationRuntime` consumes the committed journal locally and supplies automatic trigger routing plus the controller-local schedule clock. Home remains independent of Internet/cloud availability for these local semantics.

## Persistence

The proven Home state-schema ledger remains at version 5. The automation subsystem maintains a separate `automation_schema_migrations` ledger in the same SQLite database. Version 1 owns scenes, schedules, automations and run history; version 2 adds the durable local automation-runtime cursor. Runtime schema introduction initializes its cursor at the current journal head so historical device events are not replayed merely because a system upgrades to dev.5.

Automation startup restores and validates scenes, schedules and automations against current Home ownership, devices, capabilities and referenced scenes/schedules before use.

## Automation Contract v1

Machine-readable `contracts/automation.v1.json` defines supported trigger, condition, action and run-status vocabularies plus hard limits. Scenes may contain only desired-state actions. Automations may use manual, reported-state-equals, availability-equals or schedule triggers; desired/reported-state and availability conditions; and `set_desired` or `activate_scene` actions.

A trigger evaluation selects matching enabled automations in stable ID order. Actions execute in definition order. Successful multi-action state mutation and run completion are atomic. On failure, the attempt rolls back desired-state changes and records a failed run separately. One to three whole-run attempts are supported. Conditions that do not match produce a skipped history record.

Schedules persist hour/minute/weekdays and a last-fired occurrence key. The engine evaluation method requires a timezone-aware datetime and suppresses duplicate occurrences durably.

## Automation Runtime Contract v1

`contracts/automation-runtime.v1.json` defines the Development local runtime behavior. The runtime reads committed Home journal events in monotonically increasing sequence order and automatically maps:

- `device.reported_state.changed` to `reported_state_equals`, and
- `device.availability.changed` to `availability_equals`.

Same-state availability observations are intentionally not trigger events in this contract version.

The runtime keeps a durable consumer cursor and uses ordered at-least-once delivery. The cursor advances only after a source event has been handled. A process failure after a desired-state action commits but before cursor checkpoint may replay that source event. Exact crash-deduplicated delivery is therefore not claimed. This limitation is bounded in dev.5 because the current action set consists only of idempotent desired-state assignments and scene activation composed of such assignments. Future non-idempotent action families require a stronger execution/idempotency design before inclusion.

`HomeAutomationRuntime` also drives schedules in the Development process with a timezone-aware controller-local clock. This does not change the core Automation Contract's explicit evaluation API; it is a separate runtime service around it.

## Adapter Event Contract v1

`contracts/adapter-events.v1.json` defines a trusted local ingress boundary for future device-protocol adapters. `LocalAdapterEventRouter` accepts reported state and device availability observations only when:

- the adapter is registered,
- its lifecycle is `ready` or `degraded`, and
- the target device is bound to that adapter.

Accepted observations still pass through the existing capability, availability and revision contracts before they are journaled and routed locally into automation evaluation. This contract does not implement any Matter, Thread, Zigbee, Z-Wave, MQTT, BLE, LAN or vendor transport/protocol and exposes no network ingress.

## HTTP API

The Development network API remains read-only: `/livez`, `/readyz`, and `/api/v1/status`. Status may expose bounded aggregate automation counts, schema versions, runtime running/error-presence state and delivery-contract metadata, but not household values, automation definitions/history, event payloads, credentials or identities. Internal scene/automation/adapter-event methods are not authorization boundaries and are not network write routes.

## Protocol and platform boundary

Matter/Thread and all other physical device protocols remain unimplemented/unvalidated. GoreeCloud Identity, Wardveil Security, Privacy Shield, Everkeep, Manager, Mesh and Glaze UI remain applicable but blocked/unaccepted runtime integrations. Local journal-to-automation routing is not GoreeCloud Mesh integration.

## Next milestone work

Add deterministic sunrise/sunset and bounded calendar time semantics. Presence/geofence work requires a separate GoreeCloud Location and Privacy Shield design/acceptance boundary rather than treating generic local events as permission to process presence data. Then establish Matter/Thread adapter, commissioning credential, subscription and interoperability boundaries. No hardware interoperability, RC, Stable, production, security/privacy acceptance, recovery acceptance or platform conformance is claimed by this checkpoint.
