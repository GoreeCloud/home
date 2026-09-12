# GoreeCloud Home Storage and Migration Contract

`0.1.0-dev.5` uses one local SQLite database authority with two explicit schema ledgers.

## Home state schema

`schema_migrations` remains at version 5:

1. event journal,
2. durable Home/Room/Device plus desired/reported state,
3. device availability,
4. optimistic desired/reported state revisions,
5. persistent adapter registry/lifecycle.

The original event-only Development database and pre-registry adapter references retain their tested forward migration paths.

## Automation storage schema

`automation_schema_migrations` is independent and is now at version 2:

1. persistent scenes, schedules, automations and automation run history,
2. durable local automation-runtime journal cursor.

This lets automation/runtime persistence evolve without falsely renumbering or redefining the established Home state-schema contract.

When automation runtime migration 2 is first applied, the local runtime cursor is initialized to the current maximum journal sequence. Existing historical household events therefore remain historical rather than being replayed as newly active automations during the upgrade.

`HomeAutomationEngine` restores definitions on startup and validates Home ownership, device/capability references, scenes and schedules before use. Schedule duplicate-occurrence keys and execution history survive restart. `HomeAutomationRuntime` restores its consumer cursor so already handled source events are not normally reprocessed.

The runtime cursor and automation action transaction are not one single transaction because automation evaluation writes its own durable run/state records before the source-event cursor advances. Delivery is therefore explicitly ordered at-least-once, not exactly-once. A crash in that narrow boundary may replay the source event. The current action vocabulary is limited to idempotent desired-state assignments; future non-idempotent actions require stronger durable idempotency semantics.

Home state mutations issued by scenes/automations share the same database transaction and journal. Failed automation action attempts roll back their desired-state mutations before a separate failed run result is recorded.

This remains Development migration evidence only. Everkeep integration, encrypted-at-rest policy, production backup/restore, downgrade/rollback acceptance, multi-controller replication and long-term event/history retention remain incomplete.
