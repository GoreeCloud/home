from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest

from goreecloud_home.adapters import AdapterLifecycle, AdapterRecord
from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home


class AdapterTests(unittest.TestCase):
    def test_registered_adapter_is_required_for_device_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(f"{directory}/home.db")
            core = HomeCore(journal)
            core.create_home(Home("home", "Home"))
            with self.assertRaises(KeyError):
                core.register_device(
                    Device(
                        id="lamp",
                        home_id="home",
                        name="Lamp",
                        capabilities=frozenset({"light.power"}),
                        adapter="matter-main",
                    )
                )
            core.register_adapter(AdapterRecord("matter-main", "matter"))
            core.register_device(
                Device(
                    id="lamp",
                    home_id="home",
                    name="Lamp",
                    capabilities=frozenset({"light.power"}),
                    adapter="matter-main",
                )
            )
            self.assertEqual("matter-main", core.snapshot()["device_state"]["lamp"]["adapter"])
            journal.close()

    def test_adapter_lifecycle_transitions_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/home.db"
            journal = EventJournal(path)
            core = HomeCore(journal)
            core.register_adapter(AdapterRecord("matter-main", "matter"))
            first = datetime(2026, 9, 5, 20, 30, tzinfo=timezone.utc)
            core.observe_adapter_lifecycle("matter-main", "starting", observed_at=first)
            core.observe_adapter_lifecycle("matter-main", "ready")
            core.observe_adapter_lifecycle("matter-main", "ready", reason="heartbeat")
            with self.assertRaises(ValueError):
                core.observe_adapter_lifecycle("matter-main", AdapterLifecycle.REGISTERED)
            journal.close()

            reopened = EventJournal(path)
            restored = HomeCore(reopened)
            snapshot = restored.snapshot()
            self.assertEqual("ready", snapshot["adapter_state"]["matter-main"]["lifecycle"])
            self.assertEqual("heartbeat", snapshot["adapter_state"]["matter-main"]["reason"])
            self.assertEqual(1, snapshot["adapter_lifecycle_counts"]["ready"])
            event_types = [event.event_type for event in reopened.list_since()]
            self.assertIn("adapter.lifecycle.changed", event_types)
            self.assertIn("adapter.lifecycle.observed", event_types)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
