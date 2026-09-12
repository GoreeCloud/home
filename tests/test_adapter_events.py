from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from goreecloud_home.adapter_events import (
    LocalAdapterEventRouter,
    adapter_event_contract,
)
from goreecloud_home.adapters import AdapterLifecycle, AdapterRecord
from goreecloud_home.automation import Automation, AutomationAction, AutomationTrigger, RunStatus
from goreecloud_home.automation_engine import HomeAutomationEngine
from goreecloud_home.automation_runtime import HomeAutomationRuntime
from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home


class AdapterEventRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = f"{self.temp.name}/home.db"
        self.journal = EventJournal(self.path)
        self.core = HomeCore(self.journal)
        self.core.create_home(Home("home", "Home"))
        self.core.register_adapter(AdapterRecord("matter-local", "matter"))
        self.core.observe_adapter_lifecycle("matter-local", AdapterLifecycle.STARTING)
        self.core.observe_adapter_lifecycle("matter-local", AdapterLifecycle.READY)
        self.core.register_device(
            Device(
                id="sensor",
                home_id="home",
                name="Sensor",
                capabilities=frozenset({"sensor.motion"}),
                adapter="matter-local",
            )
        )
        self.core.register_device(
            Device(
                id="lamp",
                home_id="home",
                name="Lamp",
                capabilities=frozenset({"light.power"}),
            )
        )
        self.engine = HomeAutomationEngine(self.core)
        self.engine.create_automation(
            Automation(
                id="motion-light",
                home_id="home",
                name="Motion Light",
                trigger=AutomationTrigger.reported_state_equals(
                    "sensor", "sensor.motion", True
                ),
                conditions=(),
                actions=(AutomationAction.set_desired("lamp", "light.power", True),),
            )
        )
        self.runtime = HomeAutomationRuntime(self.engine)
        self.router = LocalAdapterEventRouter(self.core, self.runtime)

    def tearDown(self) -> None:
        self.journal.close()
        self.temp.cleanup()

    def test_reported_state_ingress_routes_to_automation(self) -> None:
        result = self.router.report_state(
            "matter-local", "sensor", "sensor.motion", True
        )
        self.assertEqual(1, result.state_revision)
        self.assertEqual(1, len(result.automation_runs))
        self.assertEqual(RunStatus.SUCCEEDED, result.automation_runs[0].status)
        self.assertTrue(
            self.core.snapshot()["device_state"]["lamp"]["desired"]["light.power"]
        )

    def test_ingress_rejects_device_not_bound_to_reporting_adapter(self) -> None:
        with self.assertRaisesRegex(ValueError, "not bound"):
            self.router.report_state(
                "matter-local", "lamp", "light.power", True
            )

    def test_ingress_rejects_stopped_adapter(self) -> None:
        self.core.observe_adapter_lifecycle("matter-local", AdapterLifecycle.STOPPED)
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            self.router.report_state(
                "matter-local", "sensor", "sensor.motion", True
            )

    def test_adapter_event_contract_file_matches_runtime_contract(self) -> None:
        path = Path(__file__).resolve().parents[1] / "contracts" / "adapter-events.v1.json"
        self.assertEqual(adapter_event_contract(), json.loads(path.read_text()))


if __name__ == "__main__":
    unittest.main()
