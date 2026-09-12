from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, TYPE_CHECKING
import json

from . import __version__
from .adapter_events import ADAPTER_EVENT_CONTRACT_VERSION
from .adapters import ADAPTER_CONTRACT_VERSION
from .automation import AUTOMATION_CONTRACT_VERSION
from .automation_runtime import AUTOMATION_RUNTIME_CONTRACT_VERSION
from .core import HomeCore
from .state_revision import STATE_REVISION_CONTRACT_VERSION

if TYPE_CHECKING:
    from .automation_engine import HomeAutomationEngine
    from .automation_runtime import HomeAutomationRuntime


class HomeStatusServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        core: HomeCore,
        *,
        automation_engine: HomeAutomationEngine | None = None,
        automation_runtime: HomeAutomationRuntime | None = None,
    ) -> None:
        if automation_runtime is not None and automation_engine is None:
            raise ValueError("automation runtime requires automation engine")
        self.core = core
        self.automation_engine = automation_engine
        self.automation_runtime = automation_runtime
        super().__init__(address, HomeStatusHandler)

    def ready(self) -> bool:
        if not self.core.ready():
            return False
        if self.automation_runtime is not None and not self.automation_runtime.running:
            return False
        return True


class HomeStatusHandler(BaseHTTPRequestHandler):
    server: HomeStatusServer

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path == "/livez":
            self._json(HTTPStatus.OK, {"status": "live"})
            return
        if self.path == "/readyz":
            ready = self.server.ready()
            self._json(
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                {"status": "ready" if ready else "not-ready"},
            )
            return
        if self.path == "/api/v1/status":
            snapshot = self.server.core.snapshot()
            payload: dict[str, Any] = {
                "product": "GoreeCloud Home",
                "version": __version__,
                "lifecycle": "development",
                "conformance": "nonconformant",
                "counts": {
                    "homes": snapshot["homes"],
                    "rooms": snapshot["rooms"],
                    "devices": snapshot["devices"],
                    "adapters": snapshot["adapters"],
                },
                "availability_counts": snapshot["availability_counts"],
                "adapter_lifecycle_counts": snapshot["adapter_lifecycle_counts"],
                "storage_schema_version": snapshot["storage_schema_version"],
                "capability_contract_version": snapshot[
                    "capability_contract_version"
                ],
                "state_revision_contract_version": STATE_REVISION_CONTRACT_VERSION,
                "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
                "adapter_event_contract_version": ADAPTER_EVENT_CONTRACT_VERSION,
                "automation_contract_version": AUTOMATION_CONTRACT_VERSION,
                "automation_runtime_contract_version": AUTOMATION_RUNTIME_CONTRACT_VERSION,
                "control_api": "not-exposed",
            }
            if self.server.automation_engine is not None:
                automation = self.server.automation_engine.snapshot()
                payload["automation_counts"] = {
                    "scenes": automation["scenes"],
                    "schedules": automation["schedules"],
                    "automations": automation["automations"],
                }
                payload["automation_storage_schema_version"] = automation[
                    "automation_storage_schema_version"
                ]
            if self.server.automation_runtime is not None:
                runtime = self.server.automation_runtime.snapshot()
                payload["automation_runtime"] = {
                    "running": runtime["running"],
                    "delivery_semantics": runtime["delivery_semantics"],
                    "controller_local_schedule_clock": runtime[
                        "controller_local_schedule_clock"
                    ],
                    "last_error_present": runtime["last_error"] is not None,
                }
            self._json(HTTPStatus.OK, payload)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"error": "control_api_not_exposed"},
            extra_headers={"Allow": "GET"},
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)
