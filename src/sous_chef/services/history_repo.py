"""SQLite persistence for accepted plans and meal history (research R8).

Owns every SQL statement in the project. Schema exactly per data-model.md:
a `plans` row per week plus normalized `meals` rows for the repetition
window, technique history, and recall queries.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from sous_chef.models.grocery import GroceryList
from sous_chef.models.history import CheckinResult, CookedStatus, MealHistoryEntry
from sous_chef.models.plan import WeeklyPlan, normalize_dish_name
from sous_chef.services.weeks import REPETITION_WINDOW_WEEKS, previous_week_ids


class CheckinError(Exception):
    """A cooked check-in that cannot be recorded (contracts/agent-tools.md)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class InstructionsError(Exception):
    """Cooking instructions that cannot be saved (contracts/agent-tools.md)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    week_id      TEXT PRIMARY KEY,
    status       TEXT NOT NULL CHECK (status IN ('accepted', 'final')),
    plan_json    TEXT NOT NULL,
    grocery_json TEXT NOT NULL,
    accepted_at  TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meals (
    week_id         TEXT NOT NULL REFERENCES plans(week_id) ON DELETE CASCADE,
    meal_name       TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    is_batch        INTEGER NOT NULL DEFAULT 0,
    is_stretch      INTEGER NOT NULL DEFAULT 0,
    technique       TEXT,
    cooked_status   TEXT NOT NULL DEFAULT 'planned'
                    CHECK (cooked_status IN ('planned', 'cooked', 'skipped')),
    instructions    TEXT,
    PRIMARY KEY (week_id, normalized_name)
);

CREATE INDEX IF NOT EXISTS idx_meals_cooked ON meals (cooked_status, week_id);
"""


class HistoryRepo:
    """Connection management and queries over the sous-chef SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self._db_path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(_SCHEMA)
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def save_accepted_plan(
        self, plan: WeeklyPlan, grocery: GroceryList, *, accepted_at: datetime
    ) -> int:
        """Upsert the week's plan (FR-022) and replace its meal rows.

        Superseded intra-week versions are overwritten; the first
        acceptance timestamp is kept, updated_at reflects the latest.
        Saved cooking instructions survive a mid-week re-acceptance for
        every meal whose normalized name is still in the plan.
        Returns the number of meal rows logged.
        """
        timestamp = accepted_at.isoformat()
        kept_instructions = self.instructions_for_week(plan.week_id)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO plans
                    (week_id, status, plan_json, grocery_json, accepted_at, updated_at)
                VALUES (?, 'accepted', ?, ?, ?, ?)
                ON CONFLICT(week_id) DO UPDATE SET
                    status = 'accepted',
                    plan_json = excluded.plan_json,
                    grocery_json = excluded.grocery_json,
                    updated_at = excluded.updated_at
                """,
                (
                    plan.week_id,
                    plan.model_dump_json(),
                    grocery.model_dump_json(),
                    timestamp,
                    timestamp,
                ),
            )
            self.connection.execute(
                "DELETE FROM meals WHERE week_id = ?", (plan.week_id,)
            )
            self.connection.executemany(
                """
                INSERT INTO meals
                    (week_id, meal_name, normalized_name, is_batch, is_stretch,
                     technique, cooked_status, instructions)
                VALUES (?, ?, ?, ?, ?, ?, 'planned', ?)
                """,
                [
                    (
                        plan.week_id,
                        meal.name,
                        meal.normalized_name,
                        int(meal.batch is not None),
                        int(meal.stretch is not None),
                        meal.stretch.technique if meal.stretch is not None else None,
                        kept_instructions.get(meal.normalized_name),
                    )
                    for meal in plan.meals
                ],
            )
        return len(plan.meals)

    def plan_status(self, week_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT status FROM plans WHERE week_id = ?", (week_id,)
        ).fetchone()
        return None if row is None else str(row["status"])

    def has_any_plans(self) -> bool:
        return (
            self.connection.execute("SELECT 1 FROM plans LIMIT 1").fetchone()
            is not None
        )

    def finalize_weeks_before(self, week_id: str) -> None:
        """Lazily mark past weeks final (research R11); called on lookup."""
        with self.connection:
            self.connection.execute(
                "UPDATE plans SET status = 'final' "
                "WHERE status = 'accepted' AND week_id < ?",
                (week_id,),
            )

    def cooked_dish_names_before(
        self, week_id: str, weeks: int = REPETITION_WINDOW_WEEKS
    ) -> list[str]:
        """Normalized names cooked in the `weeks` ISO weeks before `week_id`."""
        window = previous_week_ids(week_id, weeks)
        placeholders = ", ".join("?" for _ in window)
        rows = self.connection.execute(
            "SELECT DISTINCT normalized_name FROM meals "
            f"WHERE cooked_status = 'cooked' AND week_id IN ({placeholders}) "
            "ORDER BY normalized_name",
            window,
        ).fetchall()
        return [str(row["normalized_name"]) for row in rows]

    def cooked_techniques(self) -> list[str]:
        """Distinct techniques from cooked stretch meals, all history (FR-006)."""
        rows = self.connection.execute(
            "SELECT DISTINCT technique FROM meals "
            "WHERE is_stretch = 1 AND cooked_status = 'cooked' "
            "AND technique IS NOT NULL ORDER BY technique"
        ).fetchall()
        return [str(row["technique"]) for row in rows]

    def meals_for_week(self, week_id: str) -> list[MealHistoryEntry]:
        rows = self.connection.execute(
            "SELECT week_id, meal_name, normalized_name, is_batch, is_stretch, "
            "technique, cooked_status FROM meals WHERE week_id = ? "
            "ORDER BY meal_name",
            (week_id,),
        ).fetchall()
        return [_meal_entry(row) for row in rows]

    def find_meals_by_normalized_name(self, name: str) -> list[MealHistoryEntry]:
        """Past occurrences of a dish for recall (FR-024), most recent first."""
        rows = self.connection.execute(
            "SELECT week_id, meal_name, normalized_name, is_batch, is_stretch, "
            "technique, cooked_status FROM meals WHERE normalized_name = ? "
            "ORDER BY week_id DESC",
            (normalize_dish_name(name),),
        ).fetchall()
        return [_meal_entry(row) for row in rows]

    def plan_for_week(self, week_id: str) -> WeeklyPlan | None:
        """The accepted plan as stored, or None when the week has no plan.

        The cookbook renders from this — `plan_json` is the only place the
        plan's own meal order, ingredients, and source URLs survive.
        """
        row = self.connection.execute(
            "SELECT plan_json FROM plans WHERE week_id = ?", (week_id,)
        ).fetchone()
        return None if row is None else WeeklyPlan.model_validate_json(row["plan_json"])

    def instructions_for_week(self, week_id: str) -> dict[str, str]:
        """Stored cooking steps for one week, keyed by normalized name."""
        rows = self.connection.execute(
            "SELECT normalized_name, instructions FROM meals "
            "WHERE week_id = ? AND instructions IS NOT NULL",
            (week_id,),
        ).fetchall()
        return {str(row["normalized_name"]): str(row["instructions"]) for row in rows}

    def save_meal_instructions(
        self, week_id: str, meal_name: str, instructions: str
    ) -> str:
        """Write cooking steps for one meal; returns its display name.

        Idempotent — re-saving overwrites. A week's status is irrelevant:
        steps stay writable after the week goes final, which is what makes
        the cookbook's on-demand generation work for earlier weeks.
        """
        if self.plan_status(week_id) is None:
            raise InstructionsError(
                "unknown_week", f"no plan exists for week {week_id}"
            )
        normalized = normalize_dish_name(meal_name)
        row = self.connection.execute(
            "SELECT meal_name FROM meals WHERE week_id = ? AND normalized_name = ?",
            (week_id, normalized),
        ).fetchone()
        if row is None:
            raise InstructionsError(
                "unknown_meal_name", f"week {week_id} has no meal named: {meal_name}"
            )
        with self.connection:
            self.connection.execute(
                "UPDATE meals SET instructions = ? "
                "WHERE week_id = ? AND normalized_name = ?",
                (instructions, week_id, normalized),
            )
        return str(row["meal_name"])

    def meal_instructions(self, week_id: str, meal_name: str) -> str | None:
        """Stored steps for one meal, or None when none were saved."""
        row = self.connection.execute(
            "SELECT instructions FROM meals WHERE week_id = ? AND normalized_name = ?",
            (week_id, normalize_dish_name(meal_name)),
        ).fetchone()
        if row is None or row["instructions"] is None:
            return None
        return str(row["instructions"])

    def previous_accepted_week(self, week_id: str) -> str | None:
        """The nearest week before `week_id` that has a plan (cookbook nav)."""
        row = self.connection.execute(
            "SELECT week_id FROM plans WHERE week_id < ? ORDER BY week_id DESC LIMIT 1",
            (week_id,),
        ).fetchone()
        return None if row is None else str(row["week_id"])

    def next_accepted_week(self, week_id: str) -> str | None:
        """The nearest week after `week_id` that has a plan (cookbook nav)."""
        row = self.connection.execute(
            "SELECT week_id FROM plans WHERE week_id > ? ORDER BY week_id ASC LIMIT 1",
            (week_id,),
        ).fetchone()
        return None if row is None else str(row["week_id"])

    def pending_checkin_week_id(self) -> str | None:
        """The most recent final week still holding planned rows (FR-021)."""
        row = self.connection.execute(
            "SELECT p.week_id FROM plans p WHERE p.status = 'final' AND EXISTS ("
            "  SELECT 1 FROM meals m"
            "  WHERE m.week_id = p.week_id AND m.cooked_status = 'planned'"
            ") ORDER BY p.week_id DESC LIMIT 1"
        ).fetchone()
        return None if row is None else str(row["week_id"])

    def weeks_summary(self, weeks_back: int) -> list[dict[str, Any]]:
        """Per-week meal summaries for get_meal_history, most recent first."""
        week_rows = self.connection.execute(
            "SELECT week_id, status FROM plans ORDER BY week_id DESC LIMIT ?",
            (weeks_back,),
        ).fetchall()
        return [
            {
                "week_id": row["week_id"],
                "status": row["status"],
                "meals": [
                    {
                        "name": entry.meal_name,
                        "is_batch": entry.is_batch,
                        "is_stretch": entry.is_stretch,
                        "technique": entry.technique,
                        "cooked_status": entry.cooked_status.value,
                    }
                    for entry in self.meals_for_week(str(row["week_id"]))
                ],
            }
            for row in week_rows
        ]

    def record_checkin(
        self, week_id: str, cooked_meal_names: Sequence[str], *, user_skipped: bool
    ) -> CheckinResult:
        """Mark listed meals cooked and the rest of the week skipped (FR-021).

        With `user_skipped=True` every planned meal is marked cooked.
        Raises CheckinError for an unknown week, an unknown meal name, or a
        week whose check-in was already recorded.
        """
        if self.plan_status(week_id) is None:
            raise CheckinError("unknown_week", f"no plan exists for week {week_id}")
        entries = self.meals_for_week(week_id)
        planned = [e for e in entries if e.cooked_status is CookedStatus.PLANNED]
        if not planned:
            raise CheckinError(
                "already_recorded",
                f"the cooked check-in for week {week_id} was already recorded",
            )
        if user_skipped:
            cooked_normalized = {entry.normalized_name for entry in planned}
        else:
            cooked_normalized = {
                normalize_dish_name(name) for name in cooked_meal_names
            }
            unknown = cooked_normalized - {entry.normalized_name for entry in entries}
            if unknown:
                raise CheckinError(
                    "unknown_meal_name",
                    f"week {week_id} has no meal named: {', '.join(sorted(unknown))}",
                )
        cooked: list[str] = []
        skipped: list[str] = []
        with self.connection:
            for entry in planned:
                is_cooked = entry.normalized_name in cooked_normalized
                (cooked if is_cooked else skipped).append(entry.meal_name)
                self.connection.execute(
                    "UPDATE meals SET cooked_status = ? "
                    "WHERE week_id = ? AND normalized_name = ?",
                    (
                        "cooked" if is_cooked else "skipped",
                        week_id,
                        entry.normalized_name,
                    ),
                )
        return CheckinResult(week_id=week_id, cooked=cooked, skipped=skipped)


def _meal_entry(row: sqlite3.Row) -> MealHistoryEntry:
    return MealHistoryEntry(
        week_id=row["week_id"],
        meal_name=row["meal_name"],
        normalized_name=row["normalized_name"],
        is_batch=bool(row["is_batch"]),
        is_stretch=bool(row["is_stretch"]),
        technique=row["technique"],
        cooked_status=CookedStatus(row["cooked_status"]),
    )

    def __enter__(self) -> HistoryRepo:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
