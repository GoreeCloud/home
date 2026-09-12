# GoreeCloud Home Architecture

Home Core is the authoritative smart-home domain service inside one controller. Internet connectivity and GoreeCloud cloud services are not prerequisites for local state or local automation execution.

The Home state subsystem uses one SQLite authority at state schema version 5 for Home/Room/Device state, adapter lifecycle, availability, desired/reported revisions and the durable event journal.

`HomeAutomationEngine` is a bounded companion inside the same local Home process/domain boundary. It shares Home Core's SQLite connection and journal but evolves through a separate automation schema ledger. Automation schema version 1 owns scenes, schedules, automation definitions and run history; version 2 adds the durable local runtime cursor.

`HomeAutomationRuntime` consumes committed Home journal events locally in sequence order and drives the existing schedule evaluator with a timezone-aware controller-local clock. It automatically translates changed reported-state and changed availability events into existing Automation Contract v1 triggers. This local runtime does not depend on GoreeCloud Mesh and does not expose network writes.

Desired and reported state use separate optimistic revisions. Automation actions target desired state only and continue to respect the capability validation boundary. Current runtime delivery is ordered at-least-once; exact crash-deduplicated delivery is not claimed. The current idempotent desired-state action vocabulary bounds replay risk until a stronger idempotency contract is designed for future external side effects.

`LocalAdapterEventRouter` is the trusted protocol-neutral ingress seam for future physical adapters. It verifies registered adapter lifecycle and device binding before forwarding reported state or availability into Home Core. The router itself implements no Matter/Thread, Zigbee, Z-Wave, MQTT, BLE, LAN or vendor transport.

Automation Contract v1 excludes arbitrary scripts/templates and recursive automation-to-automation actions. Matching and action execution remain deterministic and bounded. Successful action sets commit atomically; failed attempts roll back their desired-state changes before failure history is recorded.

Protocol adapters remain explicit registered entities. Future Matter/Thread and other adapters will translate protocol state into the existing capability/availability/revision and adapter-event contracts. No protocol adapter currently establishes physical device interoperability.
