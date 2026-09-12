from __future__ import annotations

from datetime import datetime
from threading import Event as ThreadEvent, RLock, Thread
from typing import Callable

from .automation import AutomationRun, AutomationTrigger
from .automation_engine import HomeAutomationEngine
from .journal import Event
from .schedule_calendar_store import (
    AUTOMATION_SCHEDULE_CALENDAR_STORAGE_VERSION,
    ScheduleCalendarStore,
)

AUTOMATION_RUNTIME_CONTRACT_VERSION = "1.1"
AUTOMATION_RUNTIME_SCHEMA_VERSION = 2
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
MAX_EVENT_DRAIN = 1000
_EVENT_BATCH_SIZE = 100
_RUNTIME_CONSUMER = "local-automation-runtime"


class HomeAutomationRuntime:
    """Local journal-to-automation routing and schedule-driving runtime.

    The runtime is intentionally local-only. It consumes committed Home journal events in
    sequence order, routes supported device events into the bounded automation evaluator,
    and drives schedules from a timezone-aware controller-local clock.

    Persistent calendar bindings are enforced by the location-free
    ``ScheduleCalendarStore``. Bound schedules therefore cannot bypass their persisted
    calendar window through the default background runtime. The existing durable
    ``Schedule.last_fired_key`` remains the sole duplicate-occurrence checkpoint.

    Delivery is ordered and at-least-once. The durable cursor advances only after each
    source event has been handled. A process failure after a bounded automation action
    commits but before the cursor checkpoint may replay that source event once. This is
    acceptable for the current action model because actions only assign desired state or
    activate scenes composed of desired-state assignments; arbitrary side effects are not
    supported.
    """

    def __init__(
        self,
        engine: HomeAutomationEngine,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0.1 <= poll_interval_seconds <= 60.0:
            raise ValueError("poll_interval_seconds must be between 0.1 and 60")
        self.engine = engine
        self.journal = engine.journal
        self.database = self.journal.database
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._lock = RLock()
        self._stop = ThreadEvent()
        self._thread: Thread | None = None
        self._last_error: str | None = None
        self._ensure_schema()
        self.schedule_calendar_store = ScheduleCalendarStore(engine)

    @property
    def cursor(self) -> int:
        row = self.database.fetchone(
            "SELECT last_sequence FROM automation_runtime_state WHERE consumer=?",
            (_RUNTIME_CONSUMER,),
        )
        if row is None:
            raise RuntimeError("automation runtime cursor is missing")
        return int(row["last_sequence"])

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def drain_events(self, *, limit: int = MAX_EVENT_DRAIN) -> list[AutomationRun]:
        if not 1 <= limit <= MAX_EVENT_DRAIN:
            raise ValueError(f"limit must be between 1 and {MAX_EVENT_DRAIN}")
        with self._lock:
            runs: list[AutomationRun] = []
            processed = 0
            while processed < limit:
                remaining = limit - processed
                batch = self.journal.list_since(
                    self.cursor,
                    limit=min(_EVENT_BATCH_SIZE, remaining),
                )
                if not batch:
                    break
                for event in batch:
                    try:
                        trigger = self._trigger_from_event(event)
                        if trigger is not None:
                            runs.extend(self.engine.evaluate_trigger(trigger))
                    except Exception as exc:  # isolate a poison event from the local runtime loop
                        self._record_routing_failure(event, exc)
                    self._advance_cursor(event.sequence)
                    processed += 1
                    if processed >= limit:
                        break
            return runs

    def tick(self, at: datetime | None = None) -> list[AutomationRun]:
        current = at or self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("automation runtime clock must return a timezone-aware datetime")
        with self._lock:
            runs = self.drain_events()
            runs.extend(self.schedule_calendar_store.evaluate_schedules(current))
            # Consume schedule.fired and automation-result journal events so the durable
            # cursor remains current. Schedule triggers are executed by the calendar-aware
            # driver using the engine's existing trigger evaluator.
            runs.extend(self.drain_events())
            return runs

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._thread = Thread(
                target=self._run_loop,
                name="goreecloud-home-automation",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._stop.set()
        thread.join(timeout=max(2.0, self.poll_interval_seconds + 1.0))
        with self._lock:
            if thread.is_alive():
                raise RuntimeError("automation runtime did not stop cleanly")
            self._thread = None

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            calendar = self.schedule_calendar_store.snapshot()
            return {
                "contract_version": AUTOMATION_RUNTIME_CONTRACT_VERSION,
                "automation_storage_schema_version": self.engine.schema_version,
                "cursor": self.cursor,
                "running": self.running,
                "poll_interval_seconds": self.poll_interval_seconds,
                "last_error": self._last_error,
                "delivery_semantics": "ordered-at-least-once",
                "controller_local_schedule_clock": True,
                "calendar_binding_enforced": True,
                "calendar_binding_storage_schema_version": calendar[
                    "storage_schema_version"
                ],
                "calendar_bound_schedules": calendar["calendar_bound_schedules"],
            }

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
                self._last_error = None
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"[:512]
            self._stop.wait(self.poll_interval_seconds)

    def _trigger_from_event(self, event: Event) -> AutomationTrigger | None:
        if event.event_type == "device.reported_state.changed":
            capability = event.payload.get("capability")
            if not isinstance(capability, str) or "value" not in event.payload:
                raise ValueError("reported-state event has invalid automation payload")
            return AutomationTrigger.reported_state_equals(
                event.entity_id,
                capability,
                event.payload["value"],
            )
        if event.event_type == "device.availability.changed":
            availability = event.payload.get("availability")
            if not isinstance(availability, str):
                raise ValueError("availability event has invalid automation payload")
            return AutomationTrigger.availability_equals(event.entity_id, availability)
        return None

    def _record_routing_failure(self, event: Event, exc: Exception) -> None:
        error = f"{type(exc).__name__}: {exc}"[:512]
        self._last_error = error
        try:
            with self.journal.transaction():
                self.journal.append(
                    "automation.runtime.routing_failed",
                    event.entity_id,
                    {
                        "source_sequence": event.sequence,
                        "source_event_type": event.event_type,
                        "error": error,
                    },
                )
        except Exception:
            # Preserve the original routing error in memory even if diagnostic journaling
            # itself is unavailable. The committed source event is still cursor-bounded.
            pass

    def _advance_cursor(self, sequence: int) -> None:
        if sequence < self.cursor:
            raise RuntimeError("automation runtime cursor cannot move backwards")
        with self.journal.transaction():
            cursor = self.database.execute(
                """
                UPDATE automation_runtime_state
                SET last_sequence=?, updated_at=datetime('now')
                WHERE consumer=?
                """,
                (sequence, _RUNTIME_CONSUMER),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("automation runtime cursor update failed")

    def _ensure_schema(self) -> None:
        existing = self.database.fetchone(
            "SELECT 1 AS ok FROM automation_schema_migrations WHERE version=?",
            (AUTOMATION_RUNTIME_SCHEMA_VERSION,),
        )
        if existing is None:
            current = self.database.fetchone(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM events"
            )
            initial_cursor = int(current["sequence"]) if current else 0
            with self.journal.transaction():
                self.database.execute(
                    """
                    CREATE TABLE IF NOT EXISTS automation_runtime_state (
                        consumer TEXT PRIMARY KEY,
                        last_sequence INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                self.database.execute(
                    """
                    INSERT OR IGNORE INTO automation_runtime_state(
                        consumer, last_sequence, updated_at
                    ) VALUES (?, ?, datetime('now'))
                    """,
                    (_RUNTIME_CONSUMER, initial_cursor),
                )
                self.database.execute(
                    """
                    INSERT INTO automation_schema_migrations(version, name, applied_at)
                    VALUES (?, ?, datetime('now'))
                    """,
                    (AUTOMATION_RUNTIME_SCHEMA_VERSION, "local-runtime-cursor"),
                )
        row = self.database.fetchone(
            "SELECT 1 AS ok FROM automation_runtime_state WHERE consumer=?",
            (_RUNTIME_CONSUMER,),
        )
        if row is None:
            current = self.database.fetchone(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM events"
            )
            sequence = int(current["sequence"]) if current else 0
            with self.journal.transaction():
                self.database.execute(
                    """
                    INSERT INTO automation_runtime_state(consumer, last_sequence, updated_at)
                    VALUES (?, ?, datetime('now'))
                    """,
                    (_RUNTIME_CONSUMER, sequence),
                )


def automation_runtime_contract() -> dict[str, object]:
    return {
        "contract": "goreecloud-home-automation-runtime",
        "contract_version": AUTOMATION_RUNTIME_CONTRACT_VERSION,
        "storage_schema_version": AUTOMATION_RUNTIME_SCHEMA_VERSION,
        "event_source": "local-durable-journal",
        "first_activation_historical_replay": False,
        "delivery": {
            "ordering": "journal-sequence",
            "semantics": "at-least-once",
            "durable_cursor": True,
            "current_actions_idempotent_assignments": True,
            "poison_event_isolation": True,
        },
        "automatic_triggers": [
            "reported_state_equals",
            "availability_equals",
        ],
        "availability_observation_triggers": False,
        "schedule_driver": {
            "background": True,
            "timezone": "controller-local",
            "poll_interval_min_seconds": 0.1,
            "poll_interval_max_seconds": 60.0,
            "calendar_binding_enforced": True,
            "calendar_binding_storage_schema_version": (
                AUTOMATION_SCHEDULE_CALENDAR_STORAGE_VERSION
            ),
            "duplicate_occurrence_authority": "schedule.last_fired_key",
            "location_data_persisted": False,
        },
        "network_write_api_exposed": False,
    }
