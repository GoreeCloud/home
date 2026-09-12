from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import patch

from goreecloud_home.automation import (
    Automation,
    AutomationAction,
    AutomationCondition,
    AutomationTrigger,
    ConditionKind,
    RunStatus,
    Scene,
    SceneAction,
    Schedule,
)
from goreecloud_home.automation_engine import HomeAutomationEngine
from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home


class AutomationTests(unittest.TestCase):
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

    def test_scene_activation_is_atomic_persistent_and_ordered(self) -> None:
        self.engine.create_scene(
            Scene(
                "evening",
                "home",
                "Evening",
                (
                    SceneAction("lamp", "light.power", True),
                    SceneAction("lamp", "light.brightness", 40),
                ),
            )
        )
        self.assertEqual(2, self.engine.activate_scene("evening"))
        snapshot = self.core.snapshot()
        self.assertTrue(snapshot["device_state"]["lamp"]["desired"]["light.power"])
        self.assertEqual(40, snapshot["device_state"]["lamp"]["desired"]["light.brightness"])
        self.assertEqual(1, self.engine.snapshot()["scenes"])
        self.journal.close()

        reopened = EventJournal(self.path)
        restored = HomeCore(reopened)
        restored_engine = HomeAutomationEngine(restored)
        self.assertEqual(1, restored_engine.snapshot()["scenes"])
        self.assertEqual(2, restored_engine.activate_scene("evening"))
        events = [event.event_type for event in reopened.list_since(limit=1000)]
        self.assertGreaterEqual(events.count("scene.activated"), 2)
        reopened.close()
        self.journal = EventJournal(self.path)

    def test_reported_state_trigger_conditions_and_actions_execute_deterministically(self) -> None:
        self.engine.create_automation(
            Automation(
                id="motion-light",
                home_id="home",
                name="Motion Light",
                trigger=AutomationTrigger.reported_state_equals("motion", "sensor.motion", True),
                conditions=(
                    AutomationCondition(
                        ConditionKind.DESIRED_STATE_EQUALS,
                        "lamp",
                        capability="light.power",
                        value=False,
                    ),
                ),
                actions=(
                    AutomationAction.set_desired("lamp", "light.power", True),
                    AutomationAction.set_desired("lamp", "light.brightness", 65),
                ),
            )
        )
        self.core.set_desired_state("lamp", "light.power", False)
        runs = self.engine.evaluate_trigger(
            AutomationTrigger.reported_state_equals("motion", "sensor.motion", True)
        )
        self.assertEqual(1, len(runs))
        self.assertEqual(RunStatus.SUCCEEDED, runs[0].status)
        self.assertEqual(2, runs[0].actions_executed)
        desired = self.core.snapshot()["device_state"]["lamp"]["desired"]
        self.assertEqual({"light.power": True, "light.brightness": 65}, desired)

    def test_condition_false_records_skipped_execution(self) -> None:
        self.engine.create_automation(
            Automation(
                id="guarded",
                home_id="home",
                name="Guarded",
                trigger=AutomationTrigger.manual(),
                conditions=(
                    AutomationCondition(
                        ConditionKind.REPORTED_STATE_EQUALS,
                        "motion",
                        capability="sensor.motion",
                        value=True,
                    ),
                ),
                actions=(AutomationAction.set_desired("lamp", "light.power", True),),
            )
        )
        run = self.engine.run_automation("guarded")
        self.assertEqual(RunStatus.SKIPPED, run.status)
        self.assertNotIn("light.power", self.core.snapshot()["device_state"]["lamp"]["desired"])
        history = self.engine.list_runs(automation_id="guarded")
        self.assertEqual(RunStatus.SKIPPED, history[0].status)

    def test_schedule_fires_once_per_timezone_aware_occurrence(self) -> None:
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
        at = datetime(2026, 9, 7, 7, 30, tzinfo=timezone.utc)
        first = self.engine.evaluate_schedules(at)
        second = self.engine.evaluate_schedules(at)
        self.assertEqual(1, len(first))
        self.assertEqual([], second)
        self.assertEqual(25, self.core.snapshot()["device_state"]["lamp"]["desired"]["light.brightness"])
        self.assertEqual(1, len(self.engine.list_runs(automation_id="morning-light")))

    def test_automation_schedule_and_execution_history_survive_restart(self) -> None:
        self.engine.create_schedule(Schedule("night", "home", "Night", 22, 15))
        self.engine.create_automation(
            Automation(
                id="night-light",
                home_id="home",
                name="Night Light",
                trigger=AutomationTrigger.schedule("night"),
                conditions=(),
                actions=(AutomationAction.set_desired("lamp", "light.brightness", 10),),
            )
        )
        at = datetime(2026, 9, 7, 22, 15, tzinfo=timezone.utc)
        self.assertEqual(1, len(self.engine.evaluate_schedules(at)))
        self.journal.close()

        reopened = EventJournal(self.path)
        restored = HomeCore(reopened)
        restored_engine = HomeAutomationEngine(restored)
        snapshot = restored_engine.snapshot()
        self.assertEqual(1, snapshot["schedules"])
        self.assertEqual(1, snapshot["automations"])
        self.assertEqual([], restored_engine.evaluate_schedules(at))
        history = restored_engine.list_runs(automation_id="night-light")
        self.assertEqual(1, len(history))
        self.assertEqual(RunStatus.SUCCEEDED, history[0].status)
        reopened.close()
        self.journal = EventJournal(self.path)

    def test_failed_multi_action_run_rolls_back_desired_state_and_records_failure(self) -> None:
        automation = Automation(
            id="atomic-run",
            home_id="home",
            name="Atomic Run",
            trigger=AutomationTrigger.manual(),
            conditions=(),
            actions=(
                AutomationAction.set_desired("lamp", "light.power", True),
                AutomationAction.set_desired("lamp", "light.brightness", 80),
            ),
        )
        self.engine.create_automation(automation)
        original = self.engine._execute_action
        calls = 0

        def fail_second(action, home_id, automation_id):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated action failure")
            return original(action, home_id, automation_id)

        with patch.object(self.engine, "_execute_action", side_effect=fail_second):
            run = self.engine.run_automation("atomic-run")
        self.assertEqual(RunStatus.FAILED, run.status)
        self.assertEqual({}, self.core.snapshot()["device_state"]["lamp"]["desired"])
        row = self.journal.database.fetchone(
            "SELECT COUNT(*) AS count FROM device_state WHERE device_id='lamp' AND state_kind='desired'"
        )
        self.assertEqual(0, int(row["count"]))
        self.assertIn("simulated action failure", run.error or "")

    def test_bounded_retry_can_recover_after_atomic_failed_attempt(self) -> None:
        self.engine.create_automation(
            Automation(
                id="retry-run",
                home_id="home",
                name="Retry Run",
                trigger=AutomationTrigger.manual(),
                conditions=(),
                actions=(AutomationAction.set_desired("lamp", "light.power", True),),
                max_attempts=2,
            )
        )
        original = self.engine._execute_action
        calls = 0

        def fail_once(action, home_id, automation_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient")
            return original(action, home_id, automation_id)

        with patch.object(self.engine, "_execute_action", side_effect=fail_once):
            run = self.engine.run_automation("retry-run")
        self.assertEqual(RunStatus.SUCCEEDED, run.status)
        history = self.engine.list_runs(automation_id="retry-run")
        self.assertEqual([RunStatus.SUCCEEDED, RunStatus.FAILED], [item.status for item in history])
        self.assertTrue(self.core.snapshot()["device_state"]["lamp"]["desired"]["light.power"])


if __name__ == "__main__":
    unittest.main()
