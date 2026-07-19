"""SQLite persistence for accepted plans and meal history (research R8).

Owns every SQL statement in the project. Schema exactly per data-model.md:
a `plans` row per week plus normalized `meals` rows for the repetition
window, technique history, and recall queries.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

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

    def __enter__(self) -> HistoryRepo:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
