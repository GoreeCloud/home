from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Any
import json

from .automation import (
    MAX_AUTOMATION_RUNS_PER_TRIGGER,
    ActionKind,
    Automation,
    AutomationAction,
    AutomationCondition,
    AutomationRun,
    AutomationTrigger,
    ConditionKind,
    RunStatus,
    Scene,
    SceneAction,
    Schedule,
    TriggerKind,
    normalize_run_time,
    trigger_matches,
)
from .core import HomeCore

AUTOMATION_STORAGE_SCHEMA_VERSION = 1


class HomeAutomationEngine:
    """Bounded persistent automation engine attached to one local Home Core.

    This class intentionally has no network surface and no arbitrary code execution.
    It shares Home Core's SQLite authority and event journal while maintaining its own
    small migration ledger so automation schema evolution does not masquerade as a
    Home state-schema migration.
    """

    def __init__(self, core: HomeCore) -> None:
        self.core = core
        self.journal = core.journal
        self.database = self.journal.database
        self._lock = RLock()
        self._scenes: dict[str, Scene] = {}
        self._schedules: dict[str, Schedule] = {}
        self._automations: dict[str, Automation] = {}
        self._ensure_schema()
        self._load_and_validate()

    @property
    def schema_version(self) -> int:
        row = self.database.fetchone(
            "SELECT COALESCE(MAX(version), 0) AS version FROM automation_schema_migrations"
        )
        return int(row["version"]) if row else 0

    def create_scene(self, scene: Scene) -> None:
        with self._lock:
            if scene.id in self._scenes:
                raise ValueError(f"scene already exists: {scene.id}")
            self._validate_scene(scene)
            with self.journal.transaction():
                self.database.execute(
                    "INSERT INTO scenes(id, home_id, name, actions_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        scene.id,
                        scene.home_id,
                        scene.name,
                        self._encode([action.as_dict() for action in scene.actions]),
                        normalize_run_time(),
                    ),
                )
                self.journal.append(
                    "scene.created",
                    scene.id,
                    {"home_id": scene.home_id, "action_count": len(scene.actions)},
                )
            self._scenes[scene.id] = scene

    def create_schedule(self, schedule: Schedule) -> None:
        with self._lock:
            if schedule.id in self._schedules:
                raise ValueError(f"schedule already exists: {schedule.id}")
            self._validate_home(schedule.home_id)
            persisted = deepcopy(schedule)
            with self.journal.transaction():
                self.database.execute(
                    """
                    INSERT INTO schedules(
                        id, home_id, name, hour, minute, weekdays_json, enabled,
                        last_fired_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        persisted.id,
                        persisted.home_id,
                        persisted.name,
                        persisted.hour,
                        persisted.minute,
                        self._encode(sorted(persisted.weekdays)),
                        int(persisted.enabled),
                        persisted.last_fired_key,
                        normalize_run_time(),
                    ),
                )
                self.journal.append(
                    "schedule.created",
                    persisted.id,
                    {
                        "home_id": persisted.home_id,
                        "hour": persisted.hour,
                        "minute": persisted.minute,
                        "weekdays": sorted(persisted.weekdays),
                        "enabled": persisted.enabled,
                    },
                )
            self._schedules[persisted.id] = persisted

    def create_automation(self, automation: Automation) -> None:
        with self._lock:
            if automation.id in self._automations:
                raise ValueError(f"automation already exists: {automation.id}")
            self._validate_automation(automation)
            with self.journal.transaction():
                self.database.execute(
                    """
                    INSERT INTO automations(
                        id, home_id, name, trigger_json, conditions_json,
                        actions_json, enabled, max_attempts, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        automation.id,
                        automation.home_id,
                        automation.name,
                        self._encode(automation.trigger.as_dict()),
                        self._encode([item.as_dict() for item in automation.conditions]),
                        self._encode([item.as_dict() for item in automation.actions]),
                        int(automation.enabled),
                        automation.max_attempts,
                        normalize_run_time(),
                    ),
                )
                self.journal.append(
                    "automation.created",
                    automation.id,
                    {
                        "home_id": automation.home_id,
                        "trigger_kind": automation.trigger.kind.value,
                        "condition_count": len(automation.conditions),
                        "action_count": len(automation.actions),
                        "enabled": automation.enabled,
                        "max_attempts": automation.max_attempts,
                    },
                )
            self._automations[automation.id] = automation

    def activate_scene(self, scene_id: str, *, source: str = "manual") -> int:
        with self._lock:
            scene = self._require_scene(scene_id)
            self._validate_scene(scene)
            desired_before = self._capture_desired(scene.actions)
            try:
                with self.journal.transaction():
                    for action in scene.actions:
                        self.core.set_desired_state(
                            action.device_id, action.capability, action.value
                        )
                    self.journal.append(
                        "scene.activated",
                        scene.id,
                        {
                            "home_id": scene.home_id,
                            "source": source[:128],
                            "action_count": len(scene.actions),
                        },
                    )
            except Exception:
                self._resync_core_after_rollback(desired_before)
                raise
            return len(scene.actions)

    def run_automation(
        self,
        automation_id: str,
        *,
        trigger: AutomationTrigger | None = None,
    ) -> AutomationRun:
        with self._lock:
            automation = self._require_automation(automation_id)
            if not automation.enabled:
                raise ValueError(f"automation is disabled: {automation.id}")
            actual = trigger or AutomationTrigger.manual()
            last: AutomationRun | None = None
            for _ in range(automation.max_attempts):
                last = self._execute_once(automation, actual)
                if last.status != RunStatus.FAILED:
                    return last
            assert last is not None
            return last

    def evaluate_trigger(self, trigger: AutomationTrigger) -> list[AutomationRun]:
        with self._lock:
            matches = [
                item
                for item in sorted(self._automations.values(), key=lambda value: value.id)
                if item.enabled and trigger_matches(item.trigger, trigger)
            ]
            if len(matches) > MAX_AUTOMATION_RUNS_PER_TRIGGER:
                raise RuntimeError(
                    f"trigger matches more than {MAX_AUTOMATION_RUNS_PER_TRIGGER} automations"
                )
            return [self.run_automation(item.id, trigger=trigger) for item in matches]

    def evaluate_schedules(self, at: datetime) -> list[AutomationRun]:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("schedule evaluation requires a timezone-aware datetime")
        with self._lock:
            runs: list[AutomationRun] = []
            for schedule in sorted(self._schedules.values(), key=lambda item: item.id):
                if not schedule.is_due(at):
                    continue
                key = schedule.occurrence_key(at)
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
                        {"home_id": schedule.home_id, "occurrence_key": key},
                    )
                schedule.last_fired_key = key
                runs.extend(self.evaluate_trigger(AutomationTrigger.schedule(schedule.id)))
            return runs

    def list_runs(
        self, *, automation_id: str | None = None, limit: int = 100
    ) -> list[AutomationRun]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._lock:
            if automation_id is not None:
                self._require_automation(automation_id)
                rows = self.database.fetchall(
                    """
                    SELECT id, automation_id, trigger_json, started_at, finished_at,
                           status, actions_executed, error
                    FROM automation_runs WHERE automation_id=?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (automation_id, limit),
                )
            else:
                rows = self.database.fetchall(
                    """
                    SELECT id, automation_id, trigger_json, started_at, finished_at,
                           status, actions_executed, error
                    FROM automation_runs ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                )
            return [self._run_from_row(row) for row in rows]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "automation_storage_schema_version": self.schema_version,
                "scenes": len(self._scenes),
                "schedules": len(self._schedules),
                "automations": len(self._automations),
            }

    def _execute_once(
        self, automation: Automation, trigger: AutomationTrigger
    ) -> AutomationRun:
        started = normalize_run_time()
        with self.journal.transaction():
            run_id = self.database.insert(
                """
                INSERT INTO automation_runs(
                    automation_id, trigger_json, started_at, status, actions_executed
                ) VALUES (?, ?, ?, ?, 0)
                """,
                (
                    automation.id,
                    self._encode(trigger.as_dict()),
                    started,
                    RunStatus.RUNNING.value,
                ),
            )
            self.journal.append(
                "automation.run.started",
                automation.id,
                {"run_id": run_id, "trigger": trigger.as_dict()},
            )

        if not self._conditions_match(automation):
            finished = normalize_run_time()
            with self.journal.transaction():
                self._finish_run(run_id, finished, RunStatus.SKIPPED, 0, None)
                self.journal.append(
                    "automation.run.skipped",
                    automation.id,
                    {"run_id": run_id, "reason": "conditions_not_met"},
                )
            return AutomationRun(
                run_id, automation.id, trigger, started, finished, RunStatus.SKIPPED, 0
            )

        desired_before = self._capture_automation_desired(automation)
        executed = 0
        try:
            with self.journal.transaction():
                for action in automation.actions:
                    self._execute_action(action, automation.home_id, automation.id)
                    executed += 1
                finished = normalize_run_time()
                self._finish_run(run_id, finished, RunStatus.SUCCEEDED, executed, None)
                self.journal.append(
                    "automation.run.succeeded",
                    automation.id,
                    {"run_id": run_id, "actions_executed": executed},
                )
        except Exception as exc:
            self._resync_core_after_rollback(desired_before)
            finished = normalize_run_time()
            error = f"{type(exc).__name__}: {exc}"[:512]
            with self.journal.transaction():
                self._finish_run(run_id, finished, RunStatus.FAILED, 0, error)
                self.journal.append(
                    "automation.run.failed",
                    automation.id,
                    {"run_id": run_id, "error": error},
                )
            return AutomationRun(
                run_id,
                automation.id,
                trigger,
                started,
                finished,
                RunStatus.FAILED,
                0,
                error,
            )
        return AutomationRun(
            run_id,
            automation.id,
            trigger,
            started,
            finished,
            RunStatus.SUCCEEDED,
            executed,
        )

    def _execute_action(
        self, action: AutomationAction, home_id: str, automation_id: str
    ) -> None:
        if action.kind == ActionKind.SET_DESIRED:
            assert action.device_id is not None and action.capability is not None
            self._validate_device_home(action.device_id, home_id)
            self.core.set_desired_state(action.device_id, action.capability, action.value)
            return
        if action.kind == ActionKind.ACTIVATE_SCENE:
            assert action.scene_id is not None
            scene = self._require_scene(action.scene_id)
            if scene.home_id != home_id:
                raise ValueError("automation scene must belong to the same home")
            for scene_action in scene.actions:
                self.core.set_desired_state(
                    scene_action.device_id, scene_action.capability, scene_action.value
                )
            self.journal.append(
                "scene.activated",
                scene.id,
                {
                    "home_id": scene.home_id,
                    "source": f"automation:{automation_id}",
                    "action_count": len(scene.actions),
                },
            )
            return
        raise ValueError(f"unsupported action kind: {action.kind}")

    def _conditions_match(self, automation: Automation) -> bool:
        snapshot = self.core.snapshot()
        for condition in automation.conditions:
            state = snapshot["device_state"][condition.device_id]
            if condition.kind == ConditionKind.DESIRED_STATE_EQUALS:
                assert condition.capability is not None
                if state["desired"].get(condition.capability) != condition.value:
                    return False
            elif condition.kind == ConditionKind.REPORTED_STATE_EQUALS:
                assert condition.capability is not None
                if state["reported"].get(condition.capability) != condition.value:
                    return False
            elif condition.kind == ConditionKind.AVAILABILITY_EQUALS:
                if state["availability"] != condition.availability.value:
                    return False
        return True

    def _validate_scene(self, scene: Scene) -> None:
        self._validate_home(scene.home_id)
        for action in scene.actions:
            self._validate_device_home(action.device_id, scene.home_id)
            self.core.capabilities.validate_desired(action.capability, action.value)
            state = self.core.snapshot()["device_state"][action.device_id]
            if action.capability not in state["capabilities"]:
                raise ValueError(
                    f"device {action.device_id!r} does not expose {action.capability!r}"
                )

    def _validate_automation(self, automation: Automation) -> None:
        self._validate_home(automation.home_id)
        trigger = automation.trigger
        if trigger.kind == TriggerKind.REPORTED_STATE_EQUALS:
            assert trigger.device_id is not None and trigger.capability is not None
            self._validate_device_home(trigger.device_id, automation.home_id)
            self._validate_device_capability(trigger.device_id, trigger.capability)
            self.core.capabilities.validate_reported(trigger.capability, trigger.value)
        elif trigger.kind == TriggerKind.AVAILABILITY_EQUALS:
            assert trigger.device_id is not None
            self._validate_device_home(trigger.device_id, automation.home_id)
        elif trigger.kind == TriggerKind.SCHEDULE:
            assert trigger.schedule_id is not None
            schedule = self._require_schedule(trigger.schedule_id)
            if schedule.home_id != automation.home_id:
                raise ValueError("automation schedule must belong to the same home")

        for condition in automation.conditions:
            self._validate_device_home(condition.device_id, automation.home_id)
            if condition.capability is not None:
                self._validate_device_capability(condition.device_id, condition.capability)
                if condition.kind == ConditionKind.DESIRED_STATE_EQUALS:
                    self.core.capabilities.validate_desired(
                        condition.capability, condition.value
                    )
                elif condition.kind == ConditionKind.REPORTED_STATE_EQUALS:
                    self.core.capabilities.validate_reported(
                        condition.capability, condition.value
                    )

        for action in automation.actions:
            if action.kind == ActionKind.SET_DESIRED:
                assert action.device_id is not None and action.capability is not None
                self._validate_device_home(action.device_id, automation.home_id)
                self._validate_device_capability(action.device_id, action.capability)
                self.core.capabilities.validate_desired(action.capability, action.value)
            elif action.kind == ActionKind.ACTIVATE_SCENE:
                assert action.scene_id is not None
                scene = self._require_scene(action.scene_id)
                if scene.home_id != automation.home_id:
                    raise ValueError("automation scene must belong to the same home")

    def _validate_home(self, home_id: str) -> None:
        row = self.database.fetchone("SELECT 1 AS ok FROM homes WHERE id=?", (home_id,))
        if row is None:
            raise KeyError(f"unknown home: {home_id}")

    def _validate_device_home(self, device_id: str, home_id: str) -> None:
        snapshot = self.core.snapshot()
        try:
            state = snapshot["device_state"][device_id]
        except KeyError as exc:
            raise KeyError(f"unknown device: {device_id}") from exc
        if state["home_id"] != home_id:
            raise ValueError("automation entity must belong to the same home")

    def _validate_device_capability(self, device_id: str, capability: str) -> None:
        state = self.core.snapshot()["device_state"][device_id]
        if capability not in state["capabilities"]:
            raise ValueError(f"device {device_id!r} does not expose {capability!r}")

    def _capture_desired(
        self, actions: tuple[SceneAction, ...]
    ) -> dict[str, tuple[dict[str, Any], dict[str, int]]]:
        snapshot = self.core.snapshot()["device_state"]
        return {
            action.device_id: (
                deepcopy(snapshot[action.device_id]["desired"]),
                dict(snapshot[action.device_id]["desired_revisions"]),
            )
            for action in actions
        }

    def _capture_automation_desired(
        self, automation: Automation
    ) -> dict[str, tuple[dict[str, Any], dict[str, int]]]:
        actions: list[SceneAction] = []
        for action in automation.actions:
            if action.kind == ActionKind.SET_DESIRED:
                assert action.device_id is not None and action.capability is not None
                actions.append(SceneAction(action.device_id, action.capability, action.value))
            else:
                assert action.scene_id is not None
                actions.extend(self._require_scene(action.scene_id).actions)
        return self._capture_desired(tuple(actions))

    def _resync_core_after_rollback(
        self, before: dict[str, tuple[dict[str, Any], dict[str, int]]]
    ) -> None:
        # HomeCore mutates its in-memory projection after nested writes. When our outer
        # transaction rolls back, restore exactly the pre-attempt desired projection.
        for device_id, (state, revisions) in before.items():
            device = self.core._require_device(device_id)
            device.desired_state = deepcopy(state)
            device.desired_revisions = dict(revisions)

    def _finish_run(
        self,
        run_id: int,
        finished_at: str,
        status: RunStatus,
        actions_executed: int,
        error: str | None,
    ) -> None:
        cursor = self.database.execute(
            """
            UPDATE automation_runs
            SET finished_at=?, status=?, actions_executed=?, error=? WHERE id=?
            """,
            (finished_at, status.value, actions_executed, error, run_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"unknown automation run: {run_id}")

    def _run_from_row(self, row: Any) -> AutomationRun:
        return AutomationRun(
            id=int(row["id"]),
            automation_id=str(row["automation_id"]),
            trigger=AutomationTrigger.from_dict(json.loads(str(row["trigger_json"]))),
            started_at=str(row["started_at"]),
            finished_at=str(row["finished_at"]) if row["finished_at"] is not None else None,
            status=RunStatus(str(row["status"])),
            actions_executed=int(row["actions_executed"]),
            error=str(row["error"]) if row["error"] is not None else None,
        )

    def _load_and_validate(self) -> None:
        scenes: dict[str, Scene] = {}
        for row in self.database.fetchall(
            "SELECT id, home_id, name, actions_json FROM scenes ORDER BY id"
        ):
            scene = Scene(
                id=str(row["id"]),
                home_id=str(row["home_id"]),
                name=str(row["name"]),
                actions=tuple(
                    SceneAction.from_dict(item)
                    for item in json.loads(str(row["actions_json"]))
                ),
            )
            scenes[scene.id] = scene
        schedules: dict[str, Schedule] = {}
        for row in self.database.fetchall(
            """
            SELECT id, home_id, name, hour, minute, weekdays_json, enabled, last_fired_key
            FROM schedules ORDER BY id
            """
        ):
            schedule = Schedule(
                id=str(row["id"]),
                home_id=str(row["home_id"]),
                name=str(row["name"]),
                hour=int(row["hour"]),
                minute=int(row["minute"]),
                weekdays=frozenset(json.loads(str(row["weekdays_json"]))),
                enabled=bool(row["enabled"]),
                last_fired_key=(
                    str(row["last_fired_key"])
                    if row["last_fired_key"] is not None
                    else None
                ),
            )
            schedules[schedule.id] = schedule
        automations: dict[str, Automation] = {}
        for row in self.database.fetchall(
            """
            SELECT id, home_id, name, trigger_json, conditions_json, actions_json,
                   enabled, max_attempts
            FROM automations ORDER BY id
            """
        ):
            automation = Automation(
                id=str(row["id"]),
                home_id=str(row["home_id"]),
                name=str(row["name"]),
                trigger=AutomationTrigger.from_dict(json.loads(str(row["trigger_json"]))),
                conditions=tuple(
                    AutomationCondition.from_dict(item)
                    for item in json.loads(str(row["conditions_json"]))
                ),
                actions=tuple(
                    AutomationAction.from_dict(item)
                    for item in json.loads(str(row["actions_json"]))
                ),
                enabled=bool(row["enabled"]),
                max_attempts=int(row["max_attempts"]),
            )
            automations[automation.id] = automation
        self._scenes = scenes
        self._schedules = schedules
        for scene in scenes.values():
            self._validate_scene(scene)
        for schedule in schedules.values():
            self._validate_home(schedule.home_id)
        self._automations = automations
        for automation in automations.values():
            self._validate_automation(automation)

    def _ensure_schema(self) -> None:
        with self.journal.transaction():
            self.database.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
        existing = self.database.fetchone(
            "SELECT 1 AS ok FROM automation_schema_migrations WHERE version=1"
        )
        if existing is not None:
            return
        with self.journal.transaction():
            self.database.execute(
                """
                CREATE TABLE IF NOT EXISTS scenes (
                    id TEXT PRIMARY KEY,
                    home_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(home_id) REFERENCES homes(id) ON DELETE CASCADE
                )
                """
            )
            self.database.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    home_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    hour INTEGER NOT NULL,
                    minute INTEGER NOT NULL,
                    weekdays_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    last_fired_key TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(home_id) REFERENCES homes(id) ON DELETE CASCADE
                )
                """
            )
            self.database.execute(
                """
                CREATE TABLE IF NOT EXISTS automations (
                    id TEXT PRIMARY KEY,
                    home_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    trigger_json TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(home_id) REFERENCES homes(id) ON DELETE CASCADE
                )
                """
            )
            self.database.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    automation_id TEXT NOT NULL,
                    trigger_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    actions_executed INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    FOREIGN KEY(automation_id) REFERENCES automations(id) ON DELETE CASCADE
                )
                """
            )
            self.database.execute(
                "CREATE INDEX IF NOT EXISTS idx_automation_runs_automation ON automation_runs(automation_id, id)"
            )
            self.database.execute(
                "INSERT INTO automation_schema_migrations(version, name, applied_at) VALUES (1, ?, ?)",
                ("automation-foundation", normalize_run_time()),
            )

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )

    def _require_scene(self, scene_id: str) -> Scene:
        try:
            return self._scenes[scene_id]
        except KeyError as exc:
            raise KeyError(f"unknown scene: {scene_id}") from exc

    def _require_schedule(self, schedule_id: str) -> Schedule:
        try:
            return self._schedules[schedule_id]
        except KeyError as exc:
            raise KeyError(f"unknown schedule: {schedule_id}") from exc

    def _require_automation(self, automation_id: str) -> Automation:
        try:
            return self._automations[automation_id]
        except KeyError as exc:
            raise KeyError(f"unknown automation: {automation_id}") from exc
