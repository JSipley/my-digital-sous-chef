"""Grocery list models, derived deterministically from an accepted plan (R9)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from sous_chef.models.plan import Unit


class Quantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: float
    unit: Unit


class PackageCount(BaseModel):
    """How many fixed-size packages of an item to buy, rounded up."""

    model_config = ConfigDict(extra="forbid")

    form: str
    size_amount: float
    size_unit: Unit
    packages: int


class GroceryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    quantities: list[Quantity]
    package: PackageCount | None
    estimated_price_usd: float


class GroceryList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GroceryItem]
    estimated_total_usd: float
    budget_delta_usd: float | None
