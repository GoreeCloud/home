from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Sequence
import json
import sqlite3

from .adapters import AdapterLifecycle, AdapterRecord
from .availability import DeviceAvailability
from .models import Device, Home, Room
from .state_revision import (
    CREATE_EXPECTED_REVISION,
    INITIAL_STATE_REVISION,
    StateConflictError,
    validate_expected_revision,
)

LATEST_SCHEMA_VERSION = 5


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteHomeDatabase:
    """Shared SQLite authority for durable Home state and the event journal."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = RLock()
        self._transaction_depth = 0
        self._connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._apply_migrations()

    def close(self) -> None:
        with self._lock:
            if self._transaction_depth:
                raise RuntimeError("cannot close database during an active transaction")
            self._connection.close()

    @contextmanager
    def transaction(self) -> Iterator["SQLiteHomeDatabase"]:
        with self._lock:
            outermost = self._transaction_depth == 0
            if outermost:
                self._connection.execute("BEGIN IMMEDIATE")
            self._transaction_depth += 1
            try:
                yield self
            except Exception:
                self._transaction_depth -= 1
                if outermost:
                    self._connection.execute("ROLLBACK")
                raise
            else:
                self._transaction_depth -= 1
                if outermost:
                    self._connection.execute("COMMIT")

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.execute(sql, tuple(parameters))

    def fetchone(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(sql, tuple(parameters)).fetchone()

    def fetchall(self, sql: str, parameters: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._connection.execute(sql, tuple(parameters)).fetchall())

    def insert(self, sql: str, parameters: Sequence[Any] = ()) -> int:
        with self._lock:
            cursor = self._connection.execute(sql, tuple(parameters))
            if cursor.lastrowid is None:
                raise RuntimeError("insert did not produce a row id")
            return int(cursor.lastrowid)

    @property
    def schema_version(self) -> int:
        row = self.fetchone("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
        return int(row["version"]) if row else 0

    def ready(self) -> bool:
        row = self.fetchone("SELECT 1 AS ok")
        return bool(row and row["ok"] == 1 and self.schema_version == LATEST_SCHEMA_VERSION)

    def _apply_migrations(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row["version"])
            for row in self._connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        migrations = (
            (1, "event-journal", self._migration_1_event_journal),
            (2, "durable-domain-state", self._migration_2_domain_state),
            (3, "device-availability", self._migration_3_device_availability),
            (4, "state-revisions", self._migration_4_state_revisions),
            (5, "adapter-registry", self._migration_5_adapter_registry),
        )
        for version, name, migration in migrations:
            if version in applied:
                continue
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                migration()
                self._connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, _utc_now()),
                )
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")

    def _migration_1_event_journal(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_id, sequence)"
        )

    def _migration_2_domain_state(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS homes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY,
                home_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(id, home_id),
                FOREIGN KEY(home_id) REFERENCES homes(id) ON DELETE CASCADE
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                home_id TEXT NOT NULL,
                room_id TEXT,
                name TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,
                adapter TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(home_id) REFERENCES homes(id) ON DELETE CASCADE,
                FOREIGN KEY(room_id, home_id) REFERENCES rooms(id, home_id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS device_state (
                device_id TEXT NOT NULL,
                state_kind TEXT NOT NULL CHECK(state_kind IN ('desired', 'reported')),
                capability TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(device_id, state_kind, capability),
                FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_state_device ON device_state(device_id)"
        )

    def _migration_3_device_availability(self) -> None:
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(devices)").fetchall()
        }
        if "availability" not in columns:
            self._connection.execute(
                "ALTER TABLE devices ADD COLUMN availability TEXT NOT NULL DEFAULT 'unknown'"
            )
        if "availability_updated_at" not in columns:
            self._connection.execute(
                "ALTER TABLE devices ADD COLUMN availability_updated_at TEXT"
            )
        if "availability_reason" not in columns:
            self._connection.execute(
                "ALTER TABLE devices ADD COLUMN availability_reason TEXT"
            )

    def _migration_4_state_revisions(self) -> None:
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(device_state)").fetchall()
        }
        if "revision" not in columns:
            self._connection.execute(
                "ALTER TABLE device_state ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
            )

    def _migration_5_adapter_registry(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS adapters (
                id TEXT PRIMARY KEY,
                protocol TEXT NOT NULL,
                lifecycle TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reason TEXT
            )
            """
        )
        now = _utc_now()
        self._connection.execute(
            """
            INSERT OR IGNORE INTO adapters(id, protocol, lifecycle, updated_at, reason)
            SELECT DISTINCT adapter, 'unknown', 'registered', ?,
                   'migrated from pre-registry device reference'
            FROM devices
            WHERE adapter IS NOT NULL
            """,
            (now,),
        )


class SQLiteStateStore:
    """Durable projection of Home Core domain state."""

    def __init__(self, database: SQLiteHomeDatabase) -> None:
        self.database = database

    @property
    def schema_version(self) -> int:
        return self.database.schema_version

    def load(self) -> tuple[dict[str, Home], dict[str, Room], dict[str, Device]]:
        homes = {
            str(row["id"]): Home(id=str(row["id"]), name=str(row["name"]))
            for row in self.database.fetchall("SELECT id, name FROM homes ORDER BY id")
        }
        rooms = {
            str(row["id"]): Room(
                id=str(row["id"]),
                home_id=str(row["home_id"]),
                name=str(row["name"]),
            )
            for row in self.database.fetchall(
                "SELECT id, home_id, name FROM rooms ORDER BY id"
            )
        }
        devices: dict[str, Device] = {}
        for row in self.database.fetchall(
            """
            SELECT id, home_id, room_id, name, capabilities_json, adapter,
                   availability, availability_updated_at, availability_reason
            FROM devices
            ORDER BY id
            """
        ):
            device = Device(
                id=str(row["id"]),
                home_id=str(row["home_id"]),
                room_id=str(row["room_id"]) if row["room_id"] is not None else None,
                name=str(row["name"]),
                capabilities=frozenset(json.loads(str(row["capabilities_json"]))),
                adapter=str(row["adapter"]) if row["adapter"] is not None else None,
                availability=DeviceAvailability(str(row["availability"])),
                availability_updated_at=(
                    str(row["availability_updated_at"])
                    if row["availability_updated_at"] is not None
                    else None
                ),
                availability_reason=(
                    str(row["availability_reason"])
                    if row["availability_reason"] is not None
                    else None
                ),
            )
            devices[device.id] = device

        for row in self.database.fetchall(
            """
            SELECT device_id, state_kind, capability, value_json, revision
            FROM device_state
            ORDER BY device_id, state_kind, capability
            """
        ):
            device = devices.get(str(row["device_id"]))
            if device is None:
                raise RuntimeError(f"state references unknown device: {row['device_id']}")
            target = (
                device.desired_state
                if str(row["state_kind"]) == "desired"
                else device.reported_state
            )
            capability = str(row["capability"])
            target[capability] = json.loads(str(row["value_json"]))
            revisions = (
                device.desired_revisions
                if str(row["state_kind"]) == "desired"
                else device.reported_revisions
            )
            revisions[capability] = int(row["revision"])
        return homes, rooms, devices

    def load_adapters(self) -> dict[str, AdapterRecord]:
        adapters: dict[str, AdapterRecord] = {}
        for row in self.database.fetchall(
            "SELECT id, protocol, lifecycle, updated_at, reason FROM adapters ORDER BY id"
        ):
            record = AdapterRecord(
                id=str(row["id"]),
                protocol=str(row["protocol"]),
                lifecycle=AdapterLifecycle(str(row["lifecycle"])),
                updated_at=str(row["updated_at"]),
                reason=str(row["reason"]) if row["reason"] is not None else None,
            )
            adapters[record.id] = record
        return adapters

    def insert_home(self, home: Home) -> None:
        self.database.execute(
            "INSERT INTO homes(id, name, created_at) VALUES (?, ?, ?)",
            (home.id, home.name, _utc_now()),
        )

    def insert_room(self, room: Room) -> None:
        self.database.execute(
            "INSERT INTO rooms(id, home_id, name, created_at) VALUES (?, ?, ?, ?)",
            (room.id, room.home_id, room.name, _utc_now()),
        )

    def insert_device(self, device: Device) -> None:
        capabilities_json = json.dumps(
            sorted(device.capabilities),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        self.database.execute(
            """
            INSERT INTO devices(
                id, home_id, room_id, name, capabilities_json, adapter, created_at,
                availability, availability_updated_at, availability_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device.id,
                device.home_id,
                device.room_id,
                device.name,
                capabilities_json,
                device.adapter,
                _utc_now(),
                device.availability.value,
                device.availability_updated_at,
                device.availability_reason,
            ),
        )
        for capability, value in sorted(device.desired_state.items()):
            self.set_device_state(device.id, "desired", capability, value)
        for capability, value in sorted(device.reported_state.items()):
            self.set_device_state(device.id, "reported", capability, value)

    def set_device_state(
        self,
        device_id: str,
        state_kind: str,
        capability: str,
        value: Any,
        *,
        expected_revision: int | None = None,
    ) -> int:
        if state_kind not in {"desired", "reported"}:
            raise ValueError(f"invalid state kind: {state_kind}")
        expected_revision = validate_expected_revision(expected_revision)
        encoded = json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        current = self.database.fetchone(
            "SELECT revision FROM device_state WHERE device_id=? AND state_kind=? AND capability=?",
            (device_id, state_kind, capability),
        )
        if current is None:
            actual_revision = 0
            if expected_revision is not None and expected_revision != CREATE_EXPECTED_REVISION:
                raise StateConflictError(
                    device_id=device_id,
                    state_kind=state_kind,
                    capability=capability,
                    expected_revision=expected_revision,
                    actual_revision=actual_revision,
                )
            new_revision = INITIAL_STATE_REVISION
            self.database.execute(
                """
                INSERT INTO device_state(
                    device_id, state_kind, capability, value_json, updated_at, revision
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (device_id, state_kind, capability, encoded, _utc_now(), new_revision),
            )
            return new_revision

        actual_revision = int(current["revision"])
        if expected_revision is not None and expected_revision != actual_revision:
            raise StateConflictError(
                device_id=device_id,
                state_kind=state_kind,
                capability=capability,
                expected_revision=expected_revision,
                actual_revision=actual_revision,
            )
        new_revision = actual_revision + 1
        self.database.execute(
            """
            UPDATE device_state
            SET value_json=?, updated_at=?, revision=?
            WHERE device_id=? AND state_kind=? AND capability=?
            """,
            (encoded, _utc_now(), new_revision, device_id, state_kind, capability),
        )
        return new_revision

    def update_availability(
        self,
        device_id: str,
        availability: DeviceAvailability,
        observed_at: str,
        reason: str | None,
    ) -> None:
        self.database.execute(
            """
            UPDATE devices
            SET availability=?, availability_updated_at=?, availability_reason=?
            WHERE id=?
            """,
            (availability.value, observed_at, reason, device_id),
        )
    def insert_adapter(self, adapter: AdapterRecord) -> None:
        observed_at = adapter.updated_at or _utc_now()
        self.database.execute(
            "INSERT INTO adapters(id, protocol, lifecycle, updated_at, reason) VALUES (?, ?, ?, ?, ?)",
            (adapter.id, adapter.protocol, adapter.lifecycle.value, observed_at, adapter.reason),
        )

    def update_adapter_lifecycle(
        self,
        adapter_id: str,
        lifecycle: AdapterLifecycle,
        observed_at: str,
        reason: str | None,
    ) -> None:
        cursor = self.database.execute(
            "UPDATE adapters SET lifecycle=?, updated_at=?, reason=? WHERE id=?",
            (lifecycle.value, observed_at, reason, adapter_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"unknown adapter: {adapter_id}")
