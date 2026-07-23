"""Integration tests for US2 acceptance scenarios 1-4 (T030).

Accepting a plan yields one flat merged grocery list plus a computed
estimated bill, persisted to SQLite; any post-acceptance change regenerates
both. Driven through the real session loop with the fake LLM transport.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fake_llm import FakeTransport, ScriptedText, ScriptedToolCall

from sous_chef.agent.prompt import SYSTEM_PROMPT
from sous_chef.agent.session import Session
from sous_chef.agent.tools import build_tools
from sous_chef.bot.app import BotHandlers
from sous_chef.bot.formatting import render_grocery_list
from sous_chef.services.history_repo import HistoryRepo

CHAT_ID = 4242
WEEK_ID = "2026-W30"
FIXED_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def meal(
    name: str,
    *,
    protein: str = "chicken",
    servings: int = 1,
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
    ingredients: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if ingredients is None:
        ingredients = [
            {
                "name": f"{protein} cut",
                "quantity": 1.0,
                "unit": "lb",
                "estimated_price_usd": 8.0,
            }
        ]
    return {
        "name": name,
        "primary_protein": protein,
        "prep_minutes": 30,
        "servings": servings,
        "batch": batch,
        "stretch": stretch,
        "source_url": None,
        "user_requested_repeat": False,
        "ingredients": ingredients,
    }


def ingredient(name: str, quantity: float, unit: str, price: float) -> dict[str, Any]:
    return {
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "estimated_price_usd": price,
    }


def plan_payload(
    *, lunch_count: int = 2, meals: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    if meals is None:
        meals = [
            meal(
                "Chicken chili",
                batch={
                    "lunches_covered": lunch_count,
                    "total_portions": lunch_count + 1,
                },
                ingredients=[
                    ingredient("chicken thighs", 3.0, "lb", 12.0),
                    ingredient("Olive Oil", 2.0, "tbsp", 0.5),
                    ingredient("black beans", 2.0, "can", 2.4),
                ],
            ),
            meal(
                "Seared salmon",
                protein="salmon",
                stretch={"technique": "searing"},
                ingredients=[
                    ingredient("salmon fillet", 1.0, "lb", 11.0),
                    ingredient("olive oil", 1.0, "tbsp", 0.25),
                ],
            ),
            meal(
                "Turkey stir-fry",
                protein="turkey",
                ingredients=[
                    ingredient("ground turkey", 1.0, "lb", 6.5),
                    ingredient("olive oil", 1.0, "tbsp", 0.25),
                ],
            ),
        ]
    return {
        "week_id": WEEK_ID,
        "dinner_count": 3,
        "lunch_count": lunch_count,
        "diet_type": None,
        "default_servings": 1,
        "weekly_budget_usd": None,
        "meals": meals,
    }


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepo:
    return HistoryRepo(tmp_path / "story2.db")


def make_session(transport: FakeTransport, repo: HistoryRepo) -> Session:
    return Session(
        chat_id=CHAT_ID,
        transport=transport,
        repo=repo,
        system_prompt=SYSTEM_PROMPT,
        tool_factory=build_tools,
        tz=UTC,
        now=lambda: FIXED_NOW,
    )


def propose_and_accept_script(payload: dict[str, Any]) -> FakeTransport:
    return FakeTransport.scripted(
        [ScriptedToolCall("propose_plan", payload), ScriptedText("Plan!")],
        [
            ScriptedToolCall("accept_plan", {"week_id": WEEK_ID}),
            ScriptedText("Accepted — grocery list below."),
        ],
    )


class TestScenario1FlatMergedListOnAccept:
    async def test_accept_delivers_flat_merged_list_and_persists(
        self, repo: HistoryRepo
    ) -> None:
        transport = propose_and_accept_script(plan_payload())
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches")
        outcome = await session.handle_message("accept the plan")

        accepted = outcome.newly_accepted
        assert accepted is not None
        names = [item.name for item in accepted.grocery.items]
        assert len(names) == len(set(names)), "SC-003: each ingredient exactly once"
        # olive oil appears in all three meals but merges to one line.
        assert names.count("olive oil") == 1
        oil = next(i for i in accepted.grocery.items if i.name == "olive oil")
        assert [(q.amount, q.unit) for q in oil.quantities] == [(4.0, "tbsp")]

        rows = repo.connection.execute("SELECT week_id, status FROM plans").fetchall()
        assert [(row["week_id"], row["status"]) for row in rows] == [
            (WEEK_ID, "accepted")
        ]
        meal_rows = repo.connection.execute(
            "SELECT meal_name, cooked_status FROM meals WHERE week_id = ?", (WEEK_ID,)
        ).fetchall()
        assert len(meal_rows) == 3
        assert all(row["cooked_status"] == "planned" for row in meal_rows)

    async def test_nothing_persisted_before_acceptance(self, repo: HistoryRepo) -> None:
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", plan_payload()), ScriptedText("Plan!")]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("3 dinners, 2 lunches")
        assert outcome.newly_accepted is None
        assert repo.connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0


class TestScenario2QuantitiesReflectCoverage:
    async def test_batch_meal_quantities_carry_full_lunch_coverage(
        self, repo: HistoryRepo
    ) -> None:
        transport = propose_and_accept_script(plan_payload())
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches")
        outcome = await session.handle_message("accept")

        accepted = outcome.newly_accepted
        assert accepted is not None
        chicken = next(i for i in accepted.grocery.items if i.name == "chicken thighs")
        # 3 lb was scaled by the model for 2 lunches + 1 dinner; verbatim.
        assert [(q.amount, q.unit) for q in chicken.quantities] == [(3.0, "lb")]
        assert accepted.plan.batch_meal is not None
        assert accepted.plan.batch_meal.batch is not None
        assert accepted.plan.batch_meal.batch.total_portions == 3


class TestScenario3BillAccompaniesList:
    async def test_bill_is_computed_sum_and_rendered_with_items(
        self, repo: HistoryRepo
    ) -> None:
        transport = propose_and_accept_script(plan_payload())
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches")
        outcome = await session.handle_message("accept")

        accepted = outcome.newly_accepted
        assert accepted is not None
        expected_total = round(12.0 + 0.5 + 2.4 + 11.0 + 0.25 + 6.5 + 0.25, 2)
        assert accepted.grocery.estimated_total_usd == expected_total

        chunks = render_grocery_list(accepted.grocery, None)
        rendered = "\n".join(chunks)
        assert f"Estimated bill: ${expected_total:.2f}" in rendered.replace("\\", "")
        for item in accepted.grocery.items:
            assert item.name in rendered.replace("\\", "").casefold()

        result = json.loads(transport.tool_calls[-1].result)
        assert result["ok"] is True
        assert result["grocery_list"]["estimated_total_usd"] == expected_total


class TestScenario4SwapAfterAcceptanceRegenerates:
    async def test_swap_regenerates_list_and_bill_and_upserts_week(
        self, repo: HistoryRepo
    ) -> None:
        first = plan_payload()
        swapped_meals = [
            first["meals"][0],
            first["meals"][1],
            meal(
                "Pork tenderloin",
                protein="pork",
                ingredients=[ingredient("pork tenderloin", 1.5, "lb", 9.0)],
            ),
        ]
        swapped = plan_payload(meals=swapped_meals)
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", first), ScriptedText("Plan!")],
            [
                ScriptedToolCall("accept_plan", {"week_id": WEEK_ID}),
                ScriptedText("Accepted."),
            ],
            [
                ScriptedToolCall("propose_plan", swapped),
                ScriptedToolCall("accept_plan", {"week_id": WEEK_ID}),
                ScriptedText("Swapped and re-accepted."),
            ],
        )
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches")
        first_outcome = await session.handle_message("accept")
        second_outcome = await session.handle_message("swap the turkey for pork")

        assert first_outcome.newly_accepted is not None
        regenerated = second_outcome.newly_accepted
        assert regenerated is not None
        assert regenerated.grocery is not first_outcome.newly_accepted.grocery
        names = [item.name for item in regenerated.grocery.items]
        assert "pork tenderloin" in names
        assert "ground turkey" not in names
        assert (
            regenerated.grocery.estimated_total_usd
            != first_outcome.newly_accepted.grocery.estimated_total_usd
        )

        # Same week upserted: still exactly one plans row, meals replaced.
        assert repo.connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 1
        meal_names = {
            row["meal_name"]
            for row in repo.connection.execute(
                "SELECT meal_name FROM meals WHERE week_id = ?", (WEEK_ID,)
            )
        }
        assert meal_names == {"Chicken chili", "Seared salmon", "Pork tenderloin"}


class RecordingBot:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str | None]] = []

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        pass

    async def send_message(
        self, chat_id: int, text: str, parse_mode: str | None = None
    ) -> None:
        self.messages.append((text, parse_mode))


class TestBotDelivery:
    async def test_grocery_list_sent_as_separate_markdown_message(
        self, repo: HistoryRepo
    ) -> None:
        transport = propose_and_accept_script(plan_payload())
        handlers = BotHandlers(
            allowed_chat_id=CHAT_ID,
            session_factory=lambda chat_id: make_session(transport, repo),
        )
        bot = RecordingBot()
        context = SimpleNamespace(bot=bot)

        def update(text: str) -> Any:
            return SimpleNamespace(
                effective_chat=SimpleNamespace(id=CHAT_ID),
                effective_message=SimpleNamespace(text=text),
            )

        await handlers.on_text(update("3 dinners and 2 lunches"), context)
        await handlers.on_text(update("accept the plan"), context)

        grocery_messages = [
            (text, mode) for text, mode in bot.messages if "Estimated bill" in text
        ]
        assert len(grocery_messages) == 1
        text, mode = grocery_messages[0]
        assert mode == "MarkdownV2"
        assert "•" in text, "one bulleted line per item"
        # A separate message from the reply text: the reply is its own entry.
        assert any("Accepted" in m for m, _ in bot.messages)
