# GoreeCloud Home — Development User Manual

This manual covers `0.1.0-dev.5` Development Home Core, the companion automation engine, and the local automation runtime only.

## Start

```bash
PYTHONPATH=src python -m goreecloud_home --database ./home.db --listen 127.0.0.1:8765
```

The service binds to loopback by default. Home state remains at Development schema version 5. Initializing `HomeAutomationEngine` creates or validates automation storage version 1; initializing `HomeAutomationRuntime` advances the separate automation migration ledger to version 2 by adding a durable local event cursor. Both use the same SQLite authority without redefining the Home state-schema ledger.

The Development process starts the local automation runtime automatically. Its background loop uses a timezone-aware controller-local clock for schedule evaluation and drains newly committed supported Home journal events into the bounded automation evaluator.

## Diagnostics

```bash
curl http://127.0.0.1:8765/livez
curl http://127.0.0.1:8765/readyz
curl http://127.0.0.1:8765/api/v1/status
```

Status exposes bounded aggregate counts, schema/contract versions, and limited runtime health metadata. It does not expose household state values, automation definitions, execution payloads/history, adapter reasons, credentials or identities. There are no HTTP write/control endpoints.

When the Development server is created with the local automation runtime, readiness also requires that runtime thread to be running.

## Automation development API

Trusted local Python callers may create Scene, Schedule and Automation definitions through `HomeAutomationEngine` and may still invoke explicit scene activation, manual automation execution, trigger evaluation or schedule evaluation.

`HomeAutomationRuntime` adds automatic local routing for committed changed reported-state and changed availability events. Its durable cursor starts at the current journal head the first time runtime schema v2 is introduced, preventing upgrade-time historical device-event replay. Same-state availability observations do not trigger automations.

Runtime delivery is ordered at-least-once, not exactly-once. A crash in the narrow interval after an automation desired-state assignment commits but before the source-event cursor checkpoint can cause one replay. The current action model is intentionally limited to idempotent desired-state assignments and scenes composed of those assignments.

`LocalAdapterEventRouter` is a trusted local boundary for future protocol adapters. It requires a registered `ready` or `degraded` adapter and a device bound to that adapter before accepting reported-state or availability input. It does not itself implement a network protocol.

Execution history remains durable and records succeeded, failed and skipped runs. Failed action attempts roll back desired-state mutations before failure history is written. Bounded whole-run retry attempts are supported.

## Tests

```bash
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m unittest discover -s tests -v
```

No Matter/Thread, Zigbee, Z-Wave, MQTT, BLE, physical-device control, production authentication, remote access, presence/geofence integration or consumer Home UI is implemented yet.
