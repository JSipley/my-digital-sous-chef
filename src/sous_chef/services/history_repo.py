"""SQLite persistence for accepted plans and meal history (research R8).

Owns every SQL statement in the project. Schema exactly per data-model.md:
a `plans` row per week plus normalized `meals` rows for the repetition
window, technique history, and recall queries.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from types import TracebackType

from sous_chef.models.grocery import GroceryList
from sous_chef.models.plan import WeeklyPlan

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
        Returns the number of meal rows logged.
        """
        timestamp = accepted_at.isoformat()
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
                     technique, cooked_status)
                VALUES (?, ?, ?, ?, ?, ?, 'planned')
                """,
                [
                    (
                        plan.week_id,
                        meal.name,
                        meal.normalized_name,
                        int(meal.batch is not None),
                        int(meal.stretch is not None),
                        meal.stretch.technique if meal.stretch is not None else None,
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

    def __enter__(self) -> HistoryRepo:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
