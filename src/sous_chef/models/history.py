"""Meal history models — the sole source of "what the user has cooked" (FR-025)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CookedStatus(StrEnum):
    PLANNED = "planned"
    COOKED = "cooked"
    SKIPPED = "skipped"


class MealHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_id: str
    meal_name: str
    normalized_name: str
    is_batch: bool
    is_stretch: bool
    technique: str | None
    cooked_status: CookedStatus


class CheckinResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_id: str
    cooked: list[str]
    skipped: list[str]
