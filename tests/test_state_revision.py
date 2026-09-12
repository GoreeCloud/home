from __future__ import annotations

import tempfile
import unittest

from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home
from goreecloud_home.state_revision import StateConflictError


class StateRevisionTests(unittest.TestCase):
    def test_optimistic_revision_prevents_stale_desired_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(f"{directory}/home.db")
            core = HomeCore(journal)
            core.create_home(Home("home", "Home"))
            core.register_device(
                Device(
                    id="lamp",
                    home_id="home",
                    name="Lamp",
                    capabilities=frozenset({"light.brightness"}),
                )
            )
            revision_1 = core.set_desired_state(
                "lamp", "light.brightness", 25, expected_revision=0
            )
            self.assertEqual(1, revision_1)
            events_before_conflict = len(journal.list_since())
            with self.assertRaises(StateConflictError) as conflict:
                core.set_desired_state(
                    "lamp", "light.brightness", 50, expected_revision=0
                )
            self.assertEqual(1, conflict.exception.actual_revision)
            self.assertEqual(events_before_conflict, len(journal.list_since()))
            snapshot = core.snapshot()
            self.assertEqual(25, snapshot["device_state"]["lamp"]["desired"]["light.brightness"])
            self.assertEqual(1, snapshot["device_state"]["lamp"]["desired_revisions"]["light.brightness"])

            revision_2 = core.set_desired_state(
                "lamp", "light.brightness", 50, expected_revision=1
            )
            self.assertEqual(2, revision_2)
            snapshot = core.snapshot()
            self.assertEqual(50, snapshot["device_state"]["lamp"]["desired"]["light.brightness"])
            self.assertEqual(2, snapshot["device_state"]["lamp"]["desired_revisions"]["light.brightness"])
            journal.close()

    def test_revisions_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/home.db"
            journal = EventJournal(path)
            core = HomeCore(journal)
            core.create_home(Home("home", "Home"))
            core.register_device(
                Device(
                    id="switch",
                    home_id="home",
                    name="Switch",
                    capabilities=frozenset({"switch.power"}),
                )
            )
            core.set_reported_state("switch", "switch.power", False, expected_revision=0)
            core.set_reported_state("switch", "switch.power", True, expected_revision=1)
            journal.close()

            reopened = EventJournal(path)
            restored = HomeCore(reopened)
            snapshot = restored.snapshot()
            self.assertEqual(2, snapshot["device_state"]["switch"]["reported_revisions"]["switch.power"])
            reopened.close()


if __name__ == "__main__":
    unittest.main()
