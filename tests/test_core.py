from __future__ import annotations

import tempfile
import unittest

from goreecloud_home.adapters import AdapterRecord
from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home, Room


class HomeCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.journal = EventJournal(f"{self.temp.name}/events.db")
        self.core = HomeCore(self.journal)

    def tearDown(self) -> None:
        self.journal.close()
        self.temp.cleanup()

    def test_domain_and_state_flow_preserves_desired_reported_distinction(self) -> None:
        self.core.create_home(Home("main-home", "Main Home"))
        self.core.create_room(Room("living-room", "main-home", "Living Room"))
        self.core.register_adapter(AdapterRecord("test", "test"))
        self.core.register_device(
            Device(
                id="lamp-1",
                home_id="main-home",
                room_id="living-room",
                name="Lamp",
                capabilities=frozenset({"light.power", "light.brightness"}),
                adapter="test",
            )
        )
        self.core.set_desired_state("lamp-1", "light.power", True)
        snapshot = self.core.snapshot()
        self.assertTrue(snapshot["device_state"]["lamp-1"]["desired"]["light.power"])
        self.assertNotIn("light.power", snapshot["device_state"]["lamp-1"]["reported"])

        self.core.set_reported_state("lamp-1", "light.power", True)
        snapshot = self.core.snapshot()
        self.assertTrue(snapshot["device_state"]["lamp-1"]["reported"]["light.power"])
        self.assertEqual(6, len(self.journal.list_since()))

    def test_device_cannot_claim_unsupported_capability(self) -> None:
        self.core.create_home(Home("home", "Home"))
        self.core.register_device(
            Device(
                id="switch-1",
                home_id="home",
                name="Switch",
                capabilities=frozenset({"switch.power"}),
            )
        )
        with self.assertRaises(ValueError):
            self.core.set_desired_state("switch-1", "lock.state", "locked")

    def test_room_must_belong_to_same_home(self) -> None:
        self.core.create_home(Home("home-a", "A"))
        self.core.create_home(Home("home-b", "B"))
        self.core.create_room(Room("room-a", "home-a", "Room A"))
        with self.assertRaises(ValueError):
            self.core.register_device(
                Device(
                    id="sensor-1",
                    home_id="home-b",
                    room_id="room-a",
                    name="Sensor",
                    capabilities=frozenset({"sensor.motion"}),
                )
            )

    def test_capability_contract_validates_values_and_write_direction(self) -> None:
        self.core.create_home(Home("home", "Home"))
        self.core.register_device(
            Device(
                id="combo",
                home_id="home",
                name="Combo",
                capabilities=frozenset({"light.brightness", "sensor.motion"}),
            )
        )
        with self.assertRaises(ValueError):
            self.core.set_desired_state("combo", "light.brightness", 101)
        with self.assertRaises(ValueError):
            self.core.set_desired_state("combo", "sensor.motion", True)
        self.core.set_reported_state("combo", "sensor.motion", False)
        self.assertFalse(
            self.core.snapshot()["device_state"]["combo"]["reported"]["sensor.motion"]
        )

        self.core.register_device(
            Device(
                id="lock",
                home_id="home",
                name="Lock",
                capabilities=frozenset({"lock.state"}),
            )
        )
        with self.assertRaises(ValueError):
            self.core.set_desired_state("lock", "lock.state", "jammed")
        self.core.set_desired_state("lock", "lock.state", "locked")
        self.core.set_reported_state("lock", "lock.state", "jammed")


if __name__ == "__main__":
    unittest.main()
