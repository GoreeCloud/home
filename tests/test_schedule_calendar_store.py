from __future__ import annotations

from datetime import date, datetime, timezone
import tempfile
import unittest

from goreecloud_home.automation import Automation, AutomationAction, AutomationTrigger, Schedule
from goreecloud_home.automation_engine import HomeAutomationEngine
from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home
from goreecloud_home.persisted_calendar import PersistedCalendarConstraint
from goreecloud_home.schedule_calendar import PersistedScheduleCalendarBinding
from goreecloud_home.schedule_calendar_store import (
    AUTOMATION_SCHEDULE_CALENDAR_STORAGE_VERSION,
    ScheduleCalendarStore,
)


class ScheduleCalendarStoreTests(unittest.TestCase):
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
                capabilities=frozenset({"light.brightness"}),
            )
        )
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

    def tearDown(self) -> None:
        self.journal.close()
        self.temp.cleanup()

    def test_binding_persists_and_blocks_outside_calendar_window(self) -> None:
        store = ScheduleCalendarStore(self.engine)
        binding = PersistedScheduleCalendarBinding(
            schedule_id="morning",
            calendar=PersistedCalendarConstraint(date(2026, 9, 7), date(2026, 9, 7)),
        )
        store.set_binding(binding)

        outside = datetime(2026, 9, 8, 7, 30, tzinfo=timezone.utc)
        inside = datetime(2026, 9, 7, 7, 30, tzinfo=timezone.utc)
        self.assertEqual([], store.evaluate_schedules(outside))
        self.assertEqual(1, len(store.evaluate_schedules(inside)))
        self.assertEqual([], store.evaluate_schedules(inside))
        self.assertEqual(
            AUTOMATION_SCHEDULE_CALENDAR_STORAGE_VERSION,
            store.snapshot()["storage_schema_version"],
        )

        self.journal.close()
        reopened = EventJournal(self.path)
        restored_core = HomeCore(reopened)
        restored_engine = HomeAutomationEngine(restored_core)
        restored_store = ScheduleCalendarStore(restored_engine)
        self.assertIsNotNone(restored_store.binding_for("morning"))
        self.assertEqual([], restored_store.evaluate_schedules(inside))
        self.assertEqual(1, len(restored_engine.list_runs(automation_id="morning-light")))
        reopened.close()
        self.journal = EventJournal(self.path)

    def test_unbound_schedule_retains_existing_schedule_semantics(self) -> None:
        store = ScheduleCalendarStore(self.engine)
        at = datetime(2026, 9, 7, 7, 30, tzinfo=timezone.utc)
        self.assertEqual(1, len(store.evaluate_schedules(at)))
        self.assertEqual([], store.evaluate_schedules(at))

    def test_persisted_payload_contains_no_location_or_solar_fields(self) -> None:
        store = ScheduleCalendarStore(self.engine)
        store.set_binding(
            PersistedScheduleCalendarBinding(
                schedule_id="morning",
                calendar=PersistedCalendarConstraint(date(2026, 9, 7), date(2026, 9, 9)),
            )
        )
        row = self.journal.database.fetchone(
            "SELECT binding_json FROM schedule_calendar_bindings WHERE schedule_id='morning'"
        )
        payload = str(row["binding_json"])
        for forbidden in ("latitude", "longitude", "coordinates", "solar", "presence", "geofence"):
            self.assertNotIn(forbidden, payload)


if __name__ == "__main__":
    unittest.main()
