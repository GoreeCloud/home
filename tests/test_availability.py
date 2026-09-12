from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest

from goreecloud_home.availability import DeviceAvailability
from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home


class AvailabilityTests(unittest.TestCase):
    def test_transition_contract_and_same_state_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(f"{directory}/home.db")
            core = HomeCore(journal)
            core.create_home(Home("home", "Home"))
            core.register_device(
                Device(
                    id="sensor",
                    home_id="home",
                    name="Sensor",
                    capabilities=frozenset({"sensor.motion"}),
                )
            )
            first = datetime(2026, 9, 5, 20, 0, tzinfo=timezone.utc)
            second = datetime(2026, 9, 5, 20, 1, tzinfo=timezone.utc)
            core.observe_device_availability("sensor", "online", observed_at=first)
            core.observe_device_availability("sensor", "online", observed_at=second)
            core.observe_device_availability("sensor", "offline", reason="heartbeat timeout")
            with self.assertRaises(ValueError):
                core.observe_device_availability("sensor", DeviceAvailability.UNKNOWN)

            events = journal.list_since()
            self.assertEqual("device.availability.changed", events[-3].event_type)
            self.assertEqual("device.availability.observed", events[-2].event_type)
            self.assertEqual("device.availability.changed", events[-1].event_type)
            snapshot = core.snapshot()
            self.assertEqual("offline", snapshot["device_state"]["sensor"]["availability"])
            self.assertEqual(1, snapshot["availability_counts"]["offline"])
            journal.close()


if __name__ == "__main__":
    unittest.main()
