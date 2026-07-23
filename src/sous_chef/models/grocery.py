"""Grocery list models, derived deterministically from an accepted plan (R9)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Quantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: float
    unit: str


class GroceryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    quantities: list[Quantity]
    estimated_price_usd: float


class GroceryList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GroceryItem]
    estimated_total_usd: float
    budget_delta_usd: float | None
