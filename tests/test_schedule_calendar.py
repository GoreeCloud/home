from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest

from goreecloud_home.automation import Schedule
from goreecloud_home.persisted_calendar import PersistedCalendarConstraint
from goreecloud_home.schedule_calendar import (
    PERSISTED_SCHEDULE_CALENDAR_BINDING_VERSION,
    PersistedScheduleCalendarBinding,
)


class PersistedScheduleCalendarBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.central = timezone(timedelta(hours=-5))
        self.schedule = Schedule(
            id="morning",
            home_id="home-1",
            name="Morning",
            hour=8,
            minute=30,
            weekdays=frozenset(range(7)),
        )
        self.binding = PersistedScheduleCalendarBinding(
            schedule_id="morning",
            calendar=PersistedCalendarConstraint(
                date(2026, 9, 6),
                date(2026, 9, 8),
            ),
        )

    def test_round_trip_is_strict_and_location_free(self) -> None:
        encoded = self.binding.as_dict()
        self.assertEqual(PERSISTED_SCHEDULE_CALENDAR_BINDING_VERSION, encoded["schema_version"])
        self.assertNotIn("coordinates", repr(encoded))
        self.assertEqual(self.binding, PersistedScheduleCalendarBinding.from_dict(encoded))

    def test_due_requires_both_schedule_and_calendar_window(self) -> None:
        inside = datetime(2026, 9, 6, 8, 30, tzinfo=self.central)
        outside = datetime(2026, 9, 9, 8, 30, tzinfo=self.central)
        wrong_time = datetime(2026, 9, 6, 8, 31, tzinfo=self.central)

        self.assertTrue(self.binding.is_due(self.schedule, inside))
        self.assertFalse(self.binding.is_due(self.schedule, outside))
        self.assertFalse(self.binding.is_due(self.schedule, wrong_time))
        self.assertEqual(self.schedule.occurrence_key(inside), self.binding.occurrence_key(self.schedule, inside))
        self.assertIsNone(self.binding.occurrence_key(self.schedule, outside))

    def test_unfired_occurrence_reuses_schedule_checkpoint(self) -> None:
        inside = datetime(2026, 9, 6, 8, 30, tzinfo=self.central)
        key = self.schedule.occurrence_key(inside)

        self.assertEqual(key, self.binding.unfired_occurrence_key(self.schedule, inside))
        self.schedule.last_fired_key = key
        self.assertIsNone(self.binding.unfired_occurrence_key(self.schedule, inside))

        next_day = datetime(2026, 9, 7, 8, 30, tzinfo=self.central)
        self.assertEqual(
            self.schedule.occurrence_key(next_day),
            self.binding.unfired_occurrence_key(self.schedule, next_day),
        )

    def test_schedule_identity_mismatch_fails_closed(self) -> None:
        other = Schedule(
            id="other",
            home_id="home-1",
            name="Other",
            hour=8,
            minute=30,
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.binding.is_due(other, datetime(2026, 9, 6, 8, 30, tzinfo=self.central))

    def test_unknown_fields_and_future_schema_fail_closed(self) -> None:
        value = self.binding.as_dict()
        value["coordinates"] = {"latitude": 1, "longitude": 2}
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            PersistedScheduleCalendarBinding.from_dict(value)

        value = self.binding.as_dict()
        value["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "unsupported schedule calendar binding"):
            PersistedScheduleCalendarBinding.from_dict(value)

    def test_naive_occurrence_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.binding.is_due(self.schedule, datetime(2026, 9, 6, 8, 30))


if __name__ == "__main__":
    unittest.main()
