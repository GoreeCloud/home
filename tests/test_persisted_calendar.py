from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest

from goreecloud_home.persisted_calendar import (
    PERSISTED_CALENDAR_CONSTRAINT_VERSION,
    PersistedCalendarConstraint,
)
from goreecloud_home.time_semantics import CalendarDateWindow


class PersistedCalendarConstraintTests(unittest.TestCase):
    def test_round_trip_preserves_bounded_calendar_window(self) -> None:
        original = PersistedCalendarConstraint.from_window(
            CalendarDateWindow(date(2026, 9, 1), date(2026, 9, 30))
        )
        restored = PersistedCalendarConstraint.from_dict(original.as_dict())
        self.assertEqual(original, restored)
        self.assertEqual(PERSISTED_CALENDAR_CONSTRAINT_VERSION, restored.schema_version)

    def test_local_calendar_membership_uses_supplied_timezone(self) -> None:
        constraint = PersistedCalendarConstraint(
            date(2026, 9, 6),
            date(2026, 9, 6),
        )
        central = timezone(timedelta(hours=-5))
        self.assertTrue(constraint.allows(datetime(2026, 9, 6, 23, 30, tzinfo=central)))
        self.assertFalse(constraint.allows(datetime(2026, 9, 7, 0, 1, tzinfo=central)))

    def test_unknown_fields_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            PersistedCalendarConstraint.from_dict(
                {
                    "schema_version": 1,
                    "start": "2026-09-01",
                    "end": "2026-09-30",
                    "coordinates": {"latitude": 0, "longitude": 0},
                }
            )

    def test_unsupported_schema_version_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported calendar constraint"):
            PersistedCalendarConstraint.from_dict(
                {
                    "schema_version": 2,
                    "start": "2026-09-01",
                    "end": "2026-09-30",
                }
            )

    def test_invalid_or_reversed_dates_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            PersistedCalendarConstraint.from_dict(
                {
                    "schema_version": 1,
                    "start": "not-a-date",
                    "end": "2026-09-30",
                }
            )
        with self.assertRaises(ValueError):
            PersistedCalendarConstraint(
                date(2026, 9, 30),
                date(2026, 9, 1),
            )

    def test_naive_datetime_is_rejected(self) -> None:
        constraint = PersistedCalendarConstraint(date(2026, 9, 1), date(2026, 9, 30))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            constraint.allows(datetime(2026, 9, 6, 8, 0))


if __name__ == "__main__":
    unittest.main()
