from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from goreecloud_home.automation import (
    Automation,
    AutomationAction,
    AutomationTrigger,
    RunStatus,
    Schedule,
)
from goreecloud_home.automation_engine import HomeAutomationEngine
from goreecloud_home.automation_runtime import (
    HomeAutomationRuntime,
    automation_runtime_contract,
)
from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home
from goreecloud_home.persisted_calendar import PersistedCalendarConstraint
from goreecloud_home.schedule_calendar import PersistedScheduleCalendarBinding


class AutomationRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = f"{self.temp.name}/home.db"
        self.journal = EventJournal(self.path)
        self.core = HomeCore(self.journal)
        self.core.create_home(Home("home", "Home"))
        self.engine = HomeAutomationEngine(self.core)
        self.core.register_device(
            Device(
                id="lamp",
                home_id="home",
                name="Lamp",
                capabilities=frozenset({"light.power", "light.brightness"}),
            )
        )
        self.core.register_device(
            Device(
                id="motion",
                home_id="home",
                name="Motion",
                capabilities=frozenset({"sensor.motion"}),
            )
        )

    def tearDown(self) -> None:
        self.journal.close()
        self.temp.cleanup()

    def _motion_automation(self, automation_id: str = "motion-light") -> None:
        self.engine.create_automation(
            Automation(
                id=automation_id,
                home_id="home",
                name="Motion Light",
                trigger=AutomationTrigger.reported_state_equals(
                    "motion", "sensor.motion", True
                ),
                conditions=(),
                actions=(
                    AutomationAction.set_desired("lamp", "light.power", True),
                ),
            )
        )

    def test_reported_state_event_routes_automatically_once(self) -> None:
        self._motion_automation()
        runtime = HomeAutomationRuntime(self.engine)
        self.core.set_reported_state("motion", "sensor.motion", True)
        runs = runtime.drain_events()
        self.assertEqual(1, len(runs))
        self.assertEqual(RunStatus.SUCCEEDED, runs[0].status)
        self.assertTrue(
            self.core.snapshot()["device_state"]["lamp"]["desired"]["light.power"]
        )
        self.assertEqual([], runtime.drain_events())
        self.assertEqual(1, len(self.engine.list_runs(automation_id="motion-light")))

    def test_first_runtime_activation_does_not_replay_historical_device_events(self) -> None:
        self._motion_automation()
        self.core.set_reported_state("motion", "sensor.motion", True)
        runtime = HomeAutomationRuntime(self.engine)
        self.assertEqual([], runtime.drain_events())
        self.assertNotIn(
            "light.power",
            self.core.snapshot()["device_state"]["lamp"]["desired"],
        )

    def test_runtime_cursor_survives_restart_without_duplicate_execution(self) -> None:
        self._motion_automation()
        runtime = HomeAutomationRuntime(self.engine)
        self.core.set_reported_state("motion", "sensor.motion", True)
        self.assertEqual(1, len(runtime.drain_events()))
        cursor = runtime.cursor
        self.journal.close()

        reopened = EventJournal(self.path)
        restored_core = HomeCore(reopened)
        restored_engine = HomeAutomationEngine(restored_core)
        restored_runtime = HomeAutomationRuntime(restored_engine)
        self.assertEqual(cursor, restored_runtime.cursor)
        self.assertEqual([], restored_runtime.drain_events())
        self.assertEqual(1, len(restored_engine.list_runs(automation_id="motion-light")))
        reopened.close()
        self.journal = EventJournal(self.path)

    def test_availability_change_routes_but_same_state_observation_does_not(self) -> None:
        self.engine.create_automation(
            Automation(
                id="motion-online",
                home_id="home",
                name="Motion Online",
                trigger=AutomationTrigger.availability_equals("motion", "online"),
                conditions=(),
                actions=(AutomationAction.set_desired("lamp", "light.power", True),),
            )
        )
        runtime = HomeAutomationRuntime(self.engine)
        self.core.observe_device_availability("motion", "online")
        self.assertEqual(1, len(runtime.drain_events()))
        self.core.observe_device_availability("motion", "online")
        self.assertEqual([], runtime.drain_events())
        self.assertEqual(1, len(self.engine.list_runs(automation_id="motion-online")))

    def test_schedule_driver_tick_uses_timezone_aware_controller_time(self) -> None:
        self.engine.create_schedule(Schedule("morning", "home", "Morning", 7, 30))
        self.engine.create_automation(
            Automation(
                id="morning-light",
                home_id="home",
                name="Morning Light",
                trigger=AutomationTrigger.schedule("morning"),
                conditions=(),
                actions=(AutomationAction.set_desired("lamp", "light.brightness", 25),),
            )
        )
        runtime = HomeAutomationRuntime(self.engine)
        at = datetime(2026, 9, 7, 7, 30, tzinfo=timezone.utc)
        first = runtime.tick(at)
        second = runtime.tick(at)
        self.assertEqual(1, len(first))
        self.assertEqual([], second)
        self.assertEqual(
            25,
            self.core.snapshot()["device_state"]["lamp"]["desired"]["light.brightness"],
        )

    def test_default_runtime_enforces_persisted_calendar_binding(self) -> None:
        self.engine.create_schedule(Schedule("morning", "home", "Morning", 7, 30))
        self.engine.create_automation(
            Automation(
                id="morning-light",
                home_id="home",
                name="Morning Light",
                trigger=AutomationTrigger.schedule("morning"),
                conditions=(),
                actions=(AutomationAction.set_desired("lamp", "light.brightness", 25),),
            )
        )
        runtime = HomeAutomationRuntime(self.engine)
        runtime.schedule_calendar_store.set_binding(
            PersistedScheduleCalendarBinding(
                schedule_id="morning",
                calendar=PersistedCalendarConstraint(
                    date(2026, 9, 7),
                    date(2026, 9, 7),
                ),
            )
        )

        outside = datetime(2026, 9, 8, 7, 30, tzinfo=timezone.utc)
        inside = datetime(2026, 9, 7, 7, 30, tzinfo=timezone.utc)
        self.assertEqual([], runtime.tick(outside))
        self.assertEqual(1, len(runtime.tick(inside)))
        self.assertEqual([], runtime.tick(inside))
        snapshot = runtime.snapshot()
        self.assertTrue(snapshot["calendar_binding_enforced"])
        self.assertEqual(3, snapshot["calendar_binding_storage_schema_version"])
        self.assertEqual(1, snapshot["calendar_bound_schedules"])

    def test_runtime_contract_file_matches_runtime_contract(self) -> None:
        path = Path(__file__).resolve().parents[1] / "contracts" / "automation-runtime.v1.json"
        self.assertEqual(automation_runtime_contract(), json.loads(path.read_text()))


if __name__ == "__main__":
    unittest.main()
