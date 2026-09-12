from __future__ import annotations

from datetime import datetime
from threading import RLock
import json

from .automation import AutomationRun, AutomationTrigger
from .automation_engine import HomeAutomationEngine
from .schedule_calendar import PersistedScheduleCalendarBinding

AUTOMATION_SCHEDULE_CALENDAR_STORAGE_VERSION = 3


class ScheduleCalendarStore:
    """Durable, location-free calendar bindings for existing Home schedules.

    This companion store uses the automation migration ledger and the same SQLite
    transaction authority as HomeAutomationEngine. It intentionally persists only
    the closed PersistedScheduleCalendarBinding contract; no coordinates, solar
    state, presence, geofence, or GoreeCloud Location data are introduced.

    ``evaluate_schedules`` is an explicit migration-safe schedule driver. Callers
    that have adopted this store should use it instead of the base engine's
    ``evaluate_schedules`` method so bound schedules cannot bypass their calendar
    window. The default Development runtime has not yet been switched to this
    driver; that final runtime wiring remains a separate acceptance step.
    """

    def __init__(self, engine: HomeAutomationEngine) -> None:
        self.engine = engine
        self.database = engine.database
        self.journal = engine.journal
        self._lock = RLock()
        self._bindings: dict[str, PersistedScheduleCalendarBinding] = {}
        self._ensure_schema()
        self._load_and_validate()

    def set_binding(self, binding: PersistedScheduleCalendarBinding) -> None:
        if not isinstance(binding, PersistedScheduleCalendarBinding):
            raise ValueError("schedule calendar store requires a persisted binding")
        with self._lock, self.engine._lock:
            schedule = self.engine._require_schedule(binding.schedule_id)
            binding._require_matching_schedule(schedule)
            encoded = json.dumps(
                binding.as_dict(),
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            with self.journal.transaction():
                self.database.execute(
                    """
                    INSERT INTO schedule_calendar_bindings(schedule_id, binding_json, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(schedule_id) DO UPDATE SET
                        binding_json=excluded.binding_json,
                        updated_at=excluded.updated_at
                    """,
                    (binding.schedule_id, encoded),
                )
                self.journal.append(
                    "schedule.calendar_binding.updated",
                    binding.schedule_id,
                    {
                        "schema_version": binding.schema_version,
                        "calendar": binding.calendar.as_dict(),
                    },
                )
            self._bindings[binding.schedule_id] = binding

    def clear_binding(self, schedule_id: str) -> bool:
        with self._lock, self.engine._lock:
            self.engine._require_schedule(schedule_id)
            with self.journal.transaction():
                cursor = self.database.execute(
                    "DELETE FROM schedule_calendar_bindings WHERE schedule_id=?",
                    (schedule_id,),
                )
                if cursor.rowcount:
                    self.journal.append(
                        "schedule.calendar_binding.cleared",
                        schedule_id,
                        {},
                    )
            self._bindings.pop(schedule_id, None)
            return bool(cursor.rowcount)

    def binding_for(self, schedule_id: str) -> PersistedScheduleCalendarBinding | None:
        with self._lock:
            return self._bindings.get(schedule_id)

    def evaluate_schedules(self, at: datetime) -> list[AutomationRun]:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("schedule evaluation requires a timezone-aware datetime")
        with self._lock, self.engine._lock:
            runs: list[AutomationRun] = []
            for schedule in sorted(self.engine._schedules.values(), key=lambda item: item.id):
                binding = self._bindings.get(schedule.id)
                if binding is None:
                    if not schedule.is_due(at):
                        continue
                    key = schedule.occurrence_key(at)
                else:
                    key = binding.occurrence_key(schedule, at)
                    if key is None:
                        continue
                if schedule.last_fired_key == key:
                    continue
                with self.journal.transaction():
                    self.database.execute(
                        "UPDATE schedules SET last_fired_key=? WHERE id=?",
                        (key, schedule.id),
                    )
                    self.journal.append(
                        "schedule.fired",
                        schedule.id,
                        {
                            "home_id": schedule.home_id,
                            "occurrence_key": key,
                            "calendar_bound": binding is not None,
                        },
                    )
                schedule.last_fired_key = key
                runs.extend(
                    self.engine.evaluate_trigger(AutomationTrigger.schedule(schedule.id))
                )
            return runs

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "storage_schema_version": AUTOMATION_SCHEDULE_CALENDAR_STORAGE_VERSION,
                "calendar_bound_schedules": len(self._bindings),
            }

    def _ensure_schema(self) -> None:
        existing = self.database.fetchone(
            "SELECT 1 AS ok FROM automation_schema_migrations WHERE version=?",
            (AUTOMATION_SCHEDULE_CALENDAR_STORAGE_VERSION,),
        )
        if existing is not None:
            return
        with self.journal.transaction():
            self.database.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_calendar_bindings (
                    schedule_id TEXT PRIMARY KEY,
                    binding_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
                )
                """
            )
            self.database.execute(
                """
                INSERT INTO automation_schema_migrations(version, name, applied_at)
                VALUES (?, ?, datetime('now'))
                """,
                (
                    AUTOMATION_SCHEDULE_CALENDAR_STORAGE_VERSION,
                    "persisted-schedule-calendar-bindings",
                ),
            )

    def _load_and_validate(self) -> None:
        bindings: dict[str, PersistedScheduleCalendarBinding] = {}
        for row in self.database.fetchall(
            "SELECT schedule_id, binding_json FROM schedule_calendar_bindings ORDER BY schedule_id"
        ):
            schedule_id = str(row["schedule_id"])
            try:
                raw = json.loads(str(row["binding_json"]))
                binding = PersistedScheduleCalendarBinding.from_dict(raw)
                schedule = self.engine._require_schedule(schedule_id)
                binding._require_matching_schedule(schedule)
            except Exception as exc:
                raise RuntimeError(
                    f"invalid persisted schedule calendar binding for {schedule_id!r}"
                ) from exc
            bindings[schedule_id] = binding
        self._bindings = bindings
