# GoreeCloud Home Automation and Runtime Contracts v1

`0.1.0-dev.5` extends the bounded GoreeCloud-owned automation foundation with a local event/schedule runtime. It still does not execute arbitrary source code, shell commands, templates, third-party scripting languages, or recursive automation-to-automation actions.

## Persistence boundary

`HomeAutomationEngine` shares Home Core's SQLite authority and durable event journal but maintains a separate `automation_schema_migrations` ledger. Home state schema remains version 5. Automation storage version 1 contains scenes, schedules, automations and execution history. Automation storage version 2 adds the durable `HomeAutomationRuntime` journal cursor.

The runtime-v2 migration initializes its cursor to the current maximum journal sequence. This makes dev.5 activation forward-looking: historical device events are not replayed simply because the runtime is first enabled.

## Automation definitions

Scenes contain ordered `set_desired` actions only. Automations contain one declarative trigger, up to 16 conditions, and up to 32 ordered actions. Automation actions are limited to `set_desired` and `activate_scene`.

Automation Contract v1 supports manual, reported-state-equals, availability-equals and schedule triggers. Conditions support desired-state-equals, reported-state-equals and availability-equals.

## Determinism and execution

`evaluate_trigger` runs matching enabled automations in stable automation-ID order. Actions execute in definition order. Runs record `running`, `succeeded`, `failed` or `skipped`. Successful action mutations and successful run completion commit atomically. If a later action fails, desired-state changes from that attempt are rolled back before a failed result is recorded separately. Automations may request one to three whole-run attempts.

A trigger evaluation may match at most 32 automations. Scenes and automations cannot invoke arbitrary automations, preventing recursive action graphs in this contract version.

## Local event routing

Automation Runtime Contract v1 uses the durable local Home journal as the source of committed trigger events. The runtime consumes events in journal-sequence order and currently maps only:

- `device.reported_state.changed` to a reported-state trigger, and
- `device.availability.changed` to an availability trigger.

`device.availability.observed` intentionally does not trigger an automation because it represents a same-state observation rather than a transition.

The durable cursor advances after each source event is handled. Delivery is therefore ordered at-least-once rather than exactly-once: if the process fails after an automation assignment commits but before the source-event cursor checkpoint, the source event can replay once after restart. Current actions are deliberately idempotent desired-state assignments (including scene actions), so this bounded replay model does not introduce an arbitrary external side effect. Any future non-idempotent action family must add stronger idempotency/deduplication semantics first.

Invalid or otherwise unrouteable source events are isolated and receive a bounded `automation.runtime.routing_failed` diagnostic event when journaling remains available; they do not permanently block later journal progress.

## Scheduling

Schedules define hour, minute, weekdays, enabled state and a durable last-fired occurrence key. Engine evaluation continues to require a timezone-aware datetime and suppresses duplicate occurrences durably across restart.

`HomeAutomationRuntime` provides the Development background clock service around that explicit API. It evaluates schedules using the controller's local timezone-aware clock at a bounded polling interval. This runtime behavior is documented separately in `contracts/automation-runtime.v1.json`; `contracts/automation.v1.json` continues to describe the underlying engine semantics.

## Adapter ingress boundary

`LocalAdapterEventRouter` provides a trusted local adapter-to-Home boundary. It requires a registered adapter in `ready` or `degraded` lifecycle state and verifies the device is bound to that adapter before accepting reported state or availability. It then commits through Home Core and drains the local runtime. This is a protocol-neutral ingress contract only; it is not Matter/Thread or other physical-protocol implementation evidence.

These remain trusted local semantics, not network authorization. The Development HTTP API remains read-only.
