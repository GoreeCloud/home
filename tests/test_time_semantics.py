from datetime import date, datetime, timedelta, timezone
import unittest

from goreecloud_home.time_semantics import (
    CalendarDateWindow,
    SolarCoordinates,
    SolarEvent,
    solar_event_utc,
    solar_events_utc,
)


class CalendarDateWindowTests(unittest.TestCase):
    def test_window_is_inclusive_and_uses_caller_timezone(self) -> None:
        window = CalendarDateWindow(date(2026, 12, 24), date(2026, 12, 26))
        central = timezone(timedelta(hours=-6))
        self.assertTrue(window.contains(datetime(2026, 12, 24, 0, 0, tzinfo=central)))
        self.assertTrue(window.contains(datetime(2026, 12, 26, 23, 59, tzinfo=central)))
        self.assertFalse(window.contains(datetime(2026, 12, 27, 0, 0, tzinfo=central)))

    def test_window_rejects_ambiguous_or_unbounded_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "end must not precede start"):
            CalendarDateWindow(date(2026, 2, 2), date(2026, 2, 1))
        with self.assertRaisesRegex(ValueError, "at most 366 days"):
            CalendarDateWindow(date(2026, 1, 1), date(2027, 1, 3))
        window = CalendarDateWindow(date(2026, 1, 1), date(2026, 1, 2))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            window.contains(datetime(2026, 1, 1, 12, 0))


class SolarTimeTests(unittest.TestCase):
    def assert_near(self, actual: datetime | None, expected: datetime, minutes: int = 5) -> None:
        self.assertIsNotNone(actual)
        assert actual is not None
        self.assertLessEqual(abs(actual - expected), timedelta(minutes=minutes))

    def test_greenwich_equinox_events_are_deterministic(self) -> None:
        coordinates = SolarCoordinates(51.4769, 0.0)
        events = solar_events_utc(date(2026, 3, 20), coordinates)
        self.assert_near(
            events[SolarEvent.SUNRISE],
            datetime(2026, 3, 20, 6, 2, tzinfo=timezone.utc),
        )
        self.assert_near(
            events[SolarEvent.SUNSET],
            datetime(2026, 3, 20, 18, 13, tzinfo=timezone.utc),
        )

    def test_solar_event_preserves_utc_date_rollover_for_local_solar_date(self) -> None:
        sydney = SolarCoordinates(-33.8688, 151.2093)
        sunrise = solar_event_utc(date(2026, 3, 20), sydney, SolarEvent.SUNRISE)
        self.assert_near(
            sunrise,
            datetime(2026, 3, 19, 19, 58, tzinfo=timezone.utc),
        )

    def test_polar_day_without_horizon_crossing_returns_none(self) -> None:
        tromso = SolarCoordinates(69.6492, 18.9553)
        self.assertIsNone(solar_event_utc(date(2026, 6, 21), tromso, SolarEvent.SUNRISE))
        self.assertIsNone(solar_event_utc(date(2026, 6, 21), tromso, SolarEvent.SUNSET))

    def test_coordinates_fail_closed_on_invalid_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "latitude"):
            SolarCoordinates(91.0, 0.0)
        with self.assertRaisesRegex(ValueError, "longitude"):
            SolarCoordinates(0.0, 181.0)
        with self.assertRaisesRegex(ValueError, "numeric"):
            SolarCoordinates(True, 0.0)


if __name__ == "__main__":
    unittest.main()
