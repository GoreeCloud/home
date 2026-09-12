# GoreeCloud Home API v1 — Development Foundation

Current network routes remain read-only local diagnostics:

- `GET /livez` — process liveness.
- `GET /readyz` — Home state SQLite authority/schema readiness and, when configured in the Development server, local automation-runtime running state.
- `GET /api/v1/status` — bounded lifecycle metadata, aggregate Home/Room/Device/adapter/availability counts, Home and automation storage schema versions, contract versions, aggregate automation definition counts, and bounded local automation-runtime state.

The status response deliberately omits household state values, state revisions, automation definitions/history, runtime cursor values, adapter reasons, device/room names, event payloads, credentials and identities. Runtime diagnostics expose only whether it is running, delivery semantics, whether a bounded error is present, and whether the controller-local schedule clock is enabled.

No HTTP write/control route is implemented in `0.1.0-dev.5`. `HomeAutomationEngine`, `HomeAutomationRuntime`, and `LocalAdapterEventRouter` are trusted local Python boundaries sharing Home Core's database/journal. Their state/automation/adapter-event methods are not network authorization surfaces.

Current versions: API `v1`, capability `1.0`, device availability `1.0`, state revision `1.0`, adapter lifecycle `1.0`, adapter event `1.0`, automation contract `1.0`, automation runtime `1.0`, Home state schema `5`, automation storage schema `2` when the local runtime is initialized.
