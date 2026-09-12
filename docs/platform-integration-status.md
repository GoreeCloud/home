# Home Platform Integration Status

Version: 0.1.0-dev.5

| Platform system | Applicability | Current status | Foundation evidence | Required next work |
| --- | --- | --- | --- | --- |
| GoreeCloud Manager | Applicable | Blocked | `/livez`, `/readyz`, bounded aggregate status including local automation-runtime state | registration, health contract consumption, acceptance |
| Privacy Shield | Applicable | Blocked | local-first privacy requirements documented; presence remains excluded from dev.5 | retention/sharing policy enforcement, Location/presence privacy contract, acceptance |
| Wardveil Security | Applicable | Blocked | loopback default; no HTTP control API; trusted local adapter ingress has lifecycle/device-binding checks | device trust, privileged-action controls, secret boundary, acceptance |
| Everkeep | Applicable | Blocked | Home schema v5 plus automation schema v2 with durable runtime cursor; recovery/export requirements documented | backup/export implementation, isolated restore including runtime-cursor behavior, acceptance |
| Glaze UI | Applicable | Blocked | product UI requirements only | Home client using required Glaze baseline, accessibility/rendered acceptance |
| GoreeCloud Mesh | Applicable | Blocked | independent durable local journal, local journal-to-automation routing and adapter boundary | Mesh capability registration, bounded cross-product events, acceptance |
| GoreeCloud Identity | Applicable | Blocked | authorization boundary documented; local automation/adapter methods remain non-network internals | household auth, sessions, roles, guest access, capability scopes, acceptance |

Local event routing is not GoreeCloud Mesh integration, lifecycle/device-binding validation is not Wardveil acceptance, and a status field is not GoreeCloud Manager integration. All seven platform systems remain blocked/unaccepted for conformance purposes at this Development checkpoint.
