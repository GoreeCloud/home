# GoreeCloud Home

GoreeCloud Home is an original, local-first GoreeCloud smart-home platform for household control, automation and standards-based device interoperability.

## Status

**Lifecycle:** Development  
**Version:** `0.1.0-dev.5`  
**Conformance:** Nonconformant  
**Repository:** `GoreeCloud/goreecloud-home`

Home Core provides durable device/state foundations, persistent declarative scenes/automations/schedules, and a bounded local automation runtime. The Development network surface remains read-only and no physical smart-home protocol interoperability is implemented yet.

## Current contracts

- Capability Contract v1
- Device Availability Contract v1
- State Revision Contract v1
- Adapter Lifecycle Contract v1
- Adapter Event Contract v1
- Automation Contract v1
- Automation Runtime Contract v1

## Automation runtime

`HomeAutomationEngine` continues to own persistent scenes, schedules, automation definitions and execution history. `HomeAutomationRuntime` consumes committed Home journal events in sequence order and automatically routes changed reported-state and changed availability events into the existing bounded evaluator. A durable runtime cursor survives restart and starts at the current journal head when first introduced, so upgrading to dev.5 does not replay older household events.

The runtime also supplies the controller-local, timezone-aware background schedule clock. Schedule duplicate-occurrence suppression remains durable. The underlying Automation Contract still accepts explicit caller evaluation; the runtime is the separate process-lifecycle component that provides autonomous local clock/event driving.

Delivery is intentionally documented as ordered **at-least-once**, not exactly-once. A crash after an automation state assignment commits but before its source-event cursor checkpoint can replay that source event. Current automation actions are limited to idempotent desired-state assignments and scene activations composed of those assignments; arbitrary code, shell, templates, external side effects and recursive automation actions remain unsupported.

`LocalAdapterEventRouter` defines a trusted local ingress boundary for future adapters. It accepts reported-state or availability observations only from a registered adapter in `ready` or `degraded` state and only for devices bound to that adapter. This boundary does not implement Matter, Thread, Zigbee, Z-Wave, MQTT, BLE, LAN or any vendor protocol.

## Deterministic time-semantics foundation

`goreecloud_home.time_semantics` now provides dependency-free deterministic sunrise/sunset calculation and bounded inclusive calendar-date windows. Solar calculations use caller-supplied coordinates only for the calculation, return UTC instants with date rollover preserved, and return no event when a polar date has no requested horizon crossing. Calendar-window evaluation requires timezone-aware datetimes and rejects reversed or greater-than-366-day spans.

These primitives are not yet wired into persisted Automation Contract schedule triggers. No household coordinates are discovered or persisted by this module, and this work does not establish GoreeCloud Location or Privacy Shield presence/geofence semantics.

## Run Development Home Core

```bash
PYTHONPATH=src python -m goreecloud_home --database ./home.db --listen 127.0.0.1:8765
```

The process starts Home Core, the persistent automation engine and the local automation runtime. Available network routes remain `GET /livez`, `GET /readyz`, and `GET /api/v1/status`; there are no HTTP write/control routes.

## Tests

```bash
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Next development

Wire the deterministic sunrise/sunset and bounded calendar primitives into persistent schedule/automation trigger semantics with migration-safe storage and duplicate-occurrence behavior. Presence/geofence work must wait for explicit GoreeCloud Location and Privacy Shield boundaries. Then begin Matter/Thread adapter boundaries, commissioning credential handling, subscriptions and interoperability fixtures, followed by the Glaze UI Home client and substantive GoreeCloud platform integrations.
