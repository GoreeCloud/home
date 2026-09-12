from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import tempfile
import unittest

from goreecloud_home.adapters import AdapterRecord
from goreecloud_home.availability import DeviceAvailability
from goreecloud_home.core import HomeCore
from goreecloud_home.journal import EventJournal
from goreecloud_home.models import Device, Home, Room
from goreecloud_home.storage import LATEST_SCHEMA_VERSION


class PersistenceTests(unittest.TestCase):
    def test_domain_state_and_availability_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/home.db"
            journal = EventJournal(path)
            core = HomeCore(journal)
            core.create_home(Home("home", "Home"))
            core.create_room(Room("kitchen", "home", "Kitchen"))
            core.register_adapter(AdapterRecord("test", "test"))
            core.register_device(
                Device(
                    id="lamp",
                    home_id="home",
                    room_id="kitchen",
                    name="Lamp",
                    capabilities=frozenset({"light.power", "light.brightness"}),
                    adapter="test",
                )
            )
            core.set_desired_state("lamp", "light.brightness", 42)
            core.set_reported_state("lamp", "light.brightness", 40)
            core.observe_device_availability(
                "lamp",
                DeviceAvailability.ONLINE,
                observed_at=datetime(2026, 9, 5, 20, 0, tzinfo=timezone.utc),
                reason="adapter heartbeat",
            )
            journal.close()

            reopened = EventJournal(path)
            restored = HomeCore(reopened)
            snapshot = restored.snapshot()
            self.assertEqual(1, snapshot["homes"])
            self.assertEqual(1, snapshot["rooms"])
            self.assertEqual(1, snapshot["devices"])
            self.assertEqual(42, snapshot["device_state"]["lamp"]["desired"]["light.brightness"])
            self.assertEqual(40, snapshot["device_state"]["lamp"]["reported"]["light.brightness"])
            self.assertEqual("online", snapshot["device_state"]["lamp"]["availability"])
            self.assertEqual("adapter heartbeat", snapshot["device_state"]["lamp"]["availability_reason"])
            self.assertEqual("registered", snapshot["adapter_state"]["test"]["lifecycle"])
            self.assertEqual(LATEST_SCHEMA_VERSION, snapshot["storage_schema_version"])
            self.assertEqual(7, len(reopened.list_since()))
            reopened.close()

    def test_existing_event_only_database_is_migrated_without_losing_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/legacy.db"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO events(event_type, entity_id, occurred_at, payload_json) VALUES (?, ?, ?, ?)",
                ("legacy.event", "legacy", "2026-09-05T00:00:00+00:00", "{}"),
            )
            connection.commit()
            connection.close()

            journal = EventJournal(path)
            core = HomeCore(journal)
            self.assertTrue(core.ready())
            self.assertEqual(LATEST_SCHEMA_VERSION, journal.database.schema_version)
            self.assertEqual("legacy.event", journal.list_since()[0].event_type)
            core.create_home(Home("home", "Home"))
            self.assertEqual(2, len(journal.list_since()))
            journal.close()

    def test_dev2_adapter_reference_is_migrated_into_adapter_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/dev2.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
                );
                INSERT INTO schema_migrations VALUES (1, 'event-journal', '2026-09-05T00:00:00+00:00');
                INSERT INTO schema_migrations VALUES (2, 'durable-domain-state', '2026-09-05T00:00:00+00:00');
                INSERT INTO schema_migrations VALUES (3, 'device-availability', '2026-09-05T00:00:00+00:00');
                CREATE TABLE events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL, occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE TABLE homes (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE rooms (
                    id TEXT PRIMARY KEY, home_id TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(id, home_id), FOREIGN KEY(home_id) REFERENCES homes(id) ON DELETE CASCADE
                );
                CREATE TABLE devices (
                    id TEXT PRIMARY KEY, home_id TEXT NOT NULL, room_id TEXT, name TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL, adapter TEXT, created_at TEXT NOT NULL,
                    availability TEXT NOT NULL DEFAULT 'unknown', availability_updated_at TEXT,
                    availability_reason TEXT, FOREIGN KEY(home_id) REFERENCES homes(id) ON DELETE CASCADE,
                    FOREIGN KEY(room_id, home_id) REFERENCES rooms(id, home_id)
                );
                CREATE TABLE device_state (
                    device_id TEXT NOT NULL, state_kind TEXT NOT NULL, capability TEXT NOT NULL,
                    value_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(device_id, state_kind, capability),
                    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE
                );
                INSERT INTO homes VALUES ('home', 'Home', '2026-09-05T00:00:00+00:00');
                INSERT INTO devices(
                    id, home_id, room_id, name, capabilities_json, adapter, created_at, availability
                ) VALUES (
                    'lamp', 'home', NULL, 'Lamp', '["light.power"]', 'legacy-adapter',
                    '2026-09-05T00:00:00+00:00', 'unknown'
                );
                """
            )
            connection.commit()
            connection.close()

            journal = EventJournal(path)
            core = HomeCore(journal)
            snapshot = core.snapshot()
            self.assertEqual(LATEST_SCHEMA_VERSION, snapshot["storage_schema_version"])
            self.assertEqual("legacy-adapter", snapshot["device_state"]["lamp"]["adapter"])
            self.assertEqual("registered", snapshot["adapter_state"]["legacy-adapter"]["lifecycle"])
            self.assertEqual("unknown", snapshot["adapter_state"]["legacy-adapter"]["protocol"])
            journal.close()

    def test_state_and_event_commit_atomically(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(f"{directory}/home.db")
            core = HomeCore(journal)
            with patch.object(journal, "append", side_effect=RuntimeError("journal failure")):
                with self.assertRaises(RuntimeError):
                    core.create_home(Home("home", "Home"))
            self.assertEqual(0, core.snapshot()["homes"])
            row = journal.database.fetchone("SELECT COUNT(*) AS count FROM homes")
            self.assertEqual(0, int(row["count"]))
            journal.close()


if __name__ == "__main__":
    unittest.main()
