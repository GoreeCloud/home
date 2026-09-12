# GoreeCloud Home Security Boundary

## Current foundation

- The Development HTTP server defaults to `127.0.0.1`.
- The HTTP surface is read-only and does not expose device registration, desired-state mutation, automation writes or adapter event ingress.
- Status output contains bounded product/lifecycle, aggregate count, schema/contract and local-runtime health metadata only.
- The repository contains no protocol credentials, enrollment secrets, private keys or production environment values.
- `LocalAdapterEventRouter` is a trusted in-process boundary only. It requires a registered adapter in `ready` or `degraded` lifecycle state and a device bound to that adapter before accepting reported-state or availability input.
- Adapter lifecycle/device binding is ordinary Home contract validation, not cryptographic device trust and not Wardveil Security acceptance.
- `HomeAutomationRuntime` consumes the local durable journal and does not open a network event/control listener.

## Privileged future capabilities

Locks, garage doors, gates, alarms, security modes, cameras, doorbells and comparable capabilities require stronger authorization and auditing than low-risk lighting controls. Future APIs and protocol ingress must receive an authenticated/verified authority context and enforce capability-specific permissions appropriate to the actor, device and risk.

## Required Wardveil work

- device/controller identity and trust
- adapter/process/service verification
- credential and key storage boundary
- network and protocol risk controls
- event authenticity/integrity where events cross trust boundaries
- privileged operation policy
- abuse/rate controls for remote surfaces
- security event audit
- integration and application acceptance

The current foundation must not be described as Wardveil-integrated, authenticated adapter ingress, or production secure.
