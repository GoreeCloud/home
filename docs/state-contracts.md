# GoreeCloud Home State Contracts

## Capability contract v1

`contracts/capabilities.v1.json` defines protocol-neutral capability semantics. Runtime definitions and the committed contract are required to match in automated tests. Definitions declare value type, write direction, ranges, units, and enumerations where applicable.

## Device availability contract v1

`contracts/device-availability.v1.json` defines `unknown`, `online`, `degraded`, and `offline` with explicit transitions. `unknown` is initial-only after a device reaches a known state. Same-state observations are journaled without pretending a transition occurred.

## State revision contract v1

`contracts/state-revision.v1.json` defines optimistic revisions for both desired and reported capability state. A new state value begins at revision `1`; callers may use `expected_revision: 0` to require creation or a positive expected revision to require an exact previous value. Every successful mutation increments by one. A stale expected revision fails with `state_revision_conflict` and commits neither state nor event.

Passing no expected revision remains an internal unconditional mutation mode. Future network control APIs must define when unconditional writes are permitted; this Development contract does not authorize them remotely.

## Adapter lifecycle contract v1

`contracts/adapter-lifecycle.v1.json` defines persistent adapter registration and lifecycle states: `registered`, `starting`, `ready`, `degraded`, `failed`, and `stopped`. Device records that name an adapter require a registered adapter record. Same-state lifecycle observations are allowed and journaled separately from transitions.

Protocol names identify an adapter boundary; they do not make that protocol implemented or interoperable. The current registry is infrastructure for future Matter/Thread and other adapters only.
