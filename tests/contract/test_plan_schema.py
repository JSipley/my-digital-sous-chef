"""Contract test: WeeklyPlan Pydantic model ⇄ weekly-plan.schema.json (T006).

The schema generated from the implementation model must match the checked-in
contract file structurally (same properties, required sets, types, refs, and
``additionalProperties: false`` throughout) so any drift fails review.
"""

import json
from pathlib import Path
from typing import Any

from sous_chef.models.plan import PlanStatus, WeeklyPlan

CONTRACT_PATH = (
    Path(__file__).parents[2]
    / "specs"
    / "001-weekly-dinner-planner"
    / "contracts"
    / "weekly-plan.schema.json"
)

STRIPPED_KEYS = {"title", "description", "$schema", "$id"}


def normalize(node: Any) -> Any:
    """Reduce a JSON schema to a canonical structural form for comparison."""
    if isinstance(node, list):
        return [normalize(item) for item in node]
    if not isinstance(node, dict):
        return node

    out = {k: normalize(v) for k, v in node.items() if k not in STRIPPED_KEYS}

    # Canonicalize nullable-type spellings: {"type": ["string", "null"]} and
    # {"anyOf": [{"type": "string"}, {"type": "null"}]} mean the same thing.
    if isinstance(out.get("type"), list):
        out["anyOf"] = [{"type": t} for t in sorted(out.pop("type"))]
    if "anyOf" in out:
        members = out["anyOf"]
        simple = [
            m for m in members if set(m) == {"type"} and isinstance(m["type"], str)
        ]
        if len(simple) == len(members):
            out["anyOf"] = sorted(members, key=lambda m: str(m["type"]))
        else:
            out["anyOf"] = sorted(members, key=json.dumps)
    if "required" in out:
        out["required"] = sorted(out["required"])
    return out


def contract_schema() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text())


def sample_payload() -> dict[str, Any]:
    def meal(
        name: str,
        batch: dict[str, Any] | None,
        stretch: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "primary_protein": "chicken",
            "prep_minutes": 35,
            "servings": 1,
            "batch": batch,
            "stretch": stretch,
            "source_url": None,
            "user_requested_repeat": False,
            "ingredients": [
                {
                    "name": "chicken thighs",
                    "quantity": 1.5,
                    "unit": "lb",
                    "estimated_price_usd": 7.5,
                }
            ],
        }

    return {
        "week_id": "2026-W30",
        "dinner_count": 3,
        "lunch_count": 2,
        "diet_type": None,
        "default_servings": 1,
        "weekly_budget_usd": None,
        "meals": [
            meal("Chicken chili", {"lunches_covered": 2, "total_portions": 3}, None),
            meal("Seared salmon", None, {"technique": "searing"}),
            meal("Turkey stir-fry", None, None),
        ],
    }


class TestSchemaPinning:
    def test_generated_schema_matches_contract(self) -> None:
        assert normalize(WeeklyPlan.model_json_schema()) == normalize(contract_schema())

    def test_additional_properties_forbidden_throughout(self) -> None:
        def object_schemas(node: Any) -> list[dict[str, Any]]:
            found = []
            if isinstance(node, dict):
                if node.get("type") == "object":
                    found.append(node)
                for value in node.values():
                    found.extend(object_schemas(value))
            elif isinstance(node, list):
                for item in node:
                    found.extend(object_schemas(item))
            return found

        generated = WeeklyPlan.model_json_schema()
        objects = object_schemas(generated)
        assert objects, "expected at least one object schema"
        for schema in objects:
            assert schema.get("additionalProperties") is False


class TestRoundTrip:
    def test_payload_round_trips_through_model(self) -> None:
        payload = sample_payload()
        plan = WeeklyPlan.model_validate(payload)
        dumped = plan.model_dump(mode="json")
        assert {key: dumped[key] for key in payload} == payload

    def test_new_plan_defaults_to_draft_status(self) -> None:
        plan = WeeklyPlan.model_validate(sample_payload())
        assert plan.status is PlanStatus.DRAFT
        assert plan.accepted_at is None
        assert set(PlanStatus) == {
            PlanStatus.DRAFT,
            PlanStatus.ACCEPTED,
            PlanStatus.FINAL,
        }

    def test_meal_normalized_name_casefolds_and_trims(self) -> None:
        plan = WeeklyPlan.model_validate(sample_payload())
        meal = plan.meals[0].model_copy(update={"name": "  Chicken  CHILI "})
        assert meal.normalized_name == "chicken chili"
