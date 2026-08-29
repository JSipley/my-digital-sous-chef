"""Integration tests for the weekly planning conversation story.

Drives the real session loop, tools, validators, and rendering through the
scripted fake LLM transport — zero network. Also asserts the
contractual ordering: the typing indicator is emitted BEFORE the agent call,
with no chat message ahead of it.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fake_llm import FakeTransport, ScriptedText, ScriptedToolCall

from sous_chef.agent.prompt import SYSTEM_PROMPT
from sous_chef.agent.session import Session
from sous_chef.agent.tools import build_tools
from sous_chef.bot.app import PRIVATE_BOT_TEXT, BotHandlers
from sous_chef.bot.formatting import render_plan
from sous_chef.services.history_repo import HistoryRepo

CHAT_ID = 4242
WEEK_ID = "2026-W30"


def meal(
    name: str,
    *,
    protein: str = "chicken",
    prep_minutes: int = 30,
    servings: int = 1,
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": protein,
        "prep_minutes": prep_minutes,
        "servings": servings,
        "batch": batch,
        "stretch": stretch,
        "source_url": source_url,
        "user_requested_repeat": False,
        "ingredients": [
            {
                "name": f"{protein} cut",
                "quantity": 1.0,
                "unit": "lb",
                "estimated_price_usd": 8.0,
            }
        ],
    }


def plan_payload(
    *,
    dinner_count: int = 3,
    lunch_count: int = 2,
    diet_type: str | None = None,
    meals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if meals is None:
        meals = [
            meal(
                "Chicken chili",
                batch={
                    "lunches_covered": lunch_count,
                    "total_portions": lunch_count + 1,
                },
            ),
            meal("Seared salmon", protein="salmon", stretch={"technique": "searing"}),
            meal("Turkey stir-fry", protein="turkey"),
        ]
    return {
        "week_id": WEEK_ID,
        "dinner_count": dinner_count,
        "lunch_count": lunch_count,
        "diet_type": diet_type,
        "default_servings": 1,
        "weekly_budget_usd": None,
        "meals": meals,
    }


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepo:
    return HistoryRepo(tmp_path / "story1.db")


def make_session(transport: FakeTransport, repo: HistoryRepo) -> Session:
    return Session(
        chat_id=CHAT_ID,
        transport=transport,
        repo=repo,
        system_prompt=SYSTEM_PROMPT,
        tool_factory=build_tools,
    )


class TestScenario1CountsOnlyProposal:
    async def test_counts_only_yields_full_plan(self, repo: HistoryRepo) -> None:
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", plan_payload()),
                ScriptedText("Here's your plan for the week!"),
            ]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message(
            "I want to cook 3 dinners and 2 lunches this week"
        )

        assert outcome.reply_text == "Here's your plan for the week!"
        plan = outcome.newly_staged_plan
        assert plan is not None
        assert plan.dinner_count == 3
        assert len(plan.meals) == 3

        result = json.loads(transport.tool_calls[0].result)
        assert result["ok"] is True and result["staged"] is True

        rendered = render_plan(plan)
        for meal_name in ("Chicken chili", "Seared salmon", "Turkey stir\\-fry"):
            assert meal_name in rendered
        # Prep time, servings, and protein on every meal, each
        # protein carrying the emoji for its own category.
        assert rendered.count("⏱") == 3
        assert rendered.count("🍽") == 3
        assert "🍗 chicken" in rendered
        assert "🐟 salmon" in rendered
        assert "🍗 turkey" in rendered


class TestScenario2FlagsStated:
    async def test_batch_and_stretch_flags_rendered(self, repo: HistoryRepo) -> None:
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", plan_payload()), ScriptedText("Plan!")]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("3 dinners, 2 lunches")
        plan = outcome.newly_staged_plan
        assert plan is not None
        rendered = render_plan(plan)
        assert rendered.count("🍲 Batch meal") == 1
        assert "covers 2 lunches" in rendered
        assert "3 portions" in rendered
        assert rendered.count("✨ Stretch meal") == 1
        assert "new technique: searing" in rendered
        # Open nights listed at the end (7 nights - 3 dinners).
        assert "Open nights: 4" in rendered


class TestScenario3SingleMealSwap:
    async def test_swap_replaces_only_the_rejected_meal(
        self, repo: HistoryRepo
    ) -> None:
        first = plan_payload()
        swapped = plan_payload(
            meals=[
                first["meals"][0],
                first["meals"][1],
                meal("Pork tenderloin", protein="pork"),
            ]
        )
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", first), ScriptedText("Plan!")],
            [ScriptedToolCall("propose_plan", swapped), ScriptedText("Swapped!")],
        )
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches")
        outcome = await session.handle_message("swap the turkey stir-fry")

        plan = outcome.newly_staged_plan
        assert plan is not None, "swap must stage a fresh draft via propose_plan"
        assert [m.name for m in plan.meals[:2]] == ["Chicken chili", "Seared salmon"]
        assert plan.meals[2].name == "Pork tenderloin"
        assert plan.dinner_count == 3 and plan.lunch_count == 2
        assert len(transport.tool_calls) == 2


class TestScenario4MissingDinnerCount:
    async def test_missing_dinner_count_prompted_before_proposing(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(
            [ScriptedText("Happy to! How many dinners (1-7) this week?")]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("plan my week")

        assert "how many" in outcome.reply_text.lower()
        assert outcome.newly_staged_plan is None
        assert session.state.staged_draft is None
        assert transport.tool_calls == []

    async def test_dinner_count_alone_plans_without_asking_about_lunches(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", plan_payload(lunch_count=0)),
                ScriptedText("Here's your plan for the week!"),
            ]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("3 dinners this week")

        plan = outcome.newly_staged_plan
        assert plan is not None, "a dinner count alone is enough to plan"
        assert plan.dinner_count == 3 and plan.lunch_count == 0
        assert "lunch" not in outcome.reply_text.lower()


class TestScenario5MidSessionPreference:
    async def test_preference_applies_without_restart(self, repo: HistoryRepo) -> None:
        pescatarian = plan_payload(
            diet_type="pescatarian",
            meals=[
                meal(
                    "Salmon chili",
                    protein="salmon",
                    batch={"lunches_covered": 2, "total_portions": 3},
                ),
                meal(
                    "Grilled trout", protein="trout", stretch={"technique": "grilling"}
                ),
                meal("Shrimp stir-fry", protein="shrimp"),
            ],
        )
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", plan_payload()), ScriptedText("Plan!")],
            [ScriptedToolCall("propose_plan", pescatarian), ScriptedText("All fish!")],
        )
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches")
        history_length = len(session.state.messages)

        outcome = await session.handle_message("actually, make it pescatarian")
        plan = outcome.newly_staged_plan
        assert plan is not None
        assert plan.diet_type == "pescatarian"
        assert session.state.diet_type == "pescatarian"
        # Same session, same conversation: history grew, it was not reset.
        assert len(session.state.messages) > history_length


class TestScenario6PriorityExplanation:
    async def test_explanation_passes_through(self, repo: HistoryRepo) -> None:
        explanation = (
            "I picked the chili for nutrition first (lean protein), then budget, "
            "then prep time, and it builds your braising skills last."
        )
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", plan_payload()), ScriptedText("Plan!")],
            [ScriptedText(explanation)],
        )
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches")
        outcome = await session.handle_message("why the chili?")
        assert outcome.reply_text == explanation
        assert outcome.newly_staged_plan is None


class RecordingBot:
    """Fake Telegram bot API recording ordering-sensitive events."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.messages: list[tuple[str, str | None]] = []

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        self.events.append(f"chat_action:{action}")

    async def send_message(
        self, chat_id: int, text: str, parse_mode: str | None = None
    ) -> None:
        self.events.append(f"message:{text[:30]}")
        self.messages.append((text, parse_mode))


def fake_update(chat_id: int, text: str) -> Any:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=SimpleNamespace(text=text),
    )


class TestBotOrderingAndDelivery:
    async def test_typing_before_agent_call_no_ack_message(
        self, repo: HistoryRepo
    ) -> None:
        events: list[str] = []
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", plan_payload()), ScriptedText("Plan!")],
            events=events,
        )
        handlers = BotHandlers(
            allowed_chat_id=CHAT_ID,
            session_factory=lambda chat_id: make_session(transport, repo),
        )
        bot = RecordingBot(events)
        update = fake_update(CHAT_ID, "3 dinners and 2 lunches please")
        await handlers.on_text(update, SimpleNamespace(bot=bot))

        agent_call = events.index("agent_call")
        typing = events.index("chat_action:typing")
        assert typing < agent_call, "typing indicator must precede the agent call"
        assert not any(e.startswith("message:") for e in events[:agent_call]), (
            "no chat message should precede the agent call"
        )

        # The rendered plan is delivered as MarkdownV2 after the agent call.
        plan_messages = [
            (text, mode) for text, mode in bot.messages if "Batch meal" in text
        ]
        assert len(plan_messages) == 1
        assert plan_messages[0][1] == "MarkdownV2"

    async def test_staging_turn_sends_only_the_rendered_plan(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", plan_payload()), ScriptedText("Plan!")]
        )
        session = make_session(transport, repo)
        handlers = BotHandlers(
            allowed_chat_id=CHAT_ID,
            session_factory=lambda chat_id: session,
        )
        bot = RecordingBot([])
        update = fake_update(CHAT_ID, "3 dinners and 2 lunches please")
        await handlers.on_text(update, SimpleNamespace(bot=bot))

        staged = session.state.staged_draft
        assert staged is not None
        # The agent's plain reply is dropped: it only restates the plan the
        # rendered message already shows.
        assert bot.messages == [(render_plan(staged), "MarkdownV2")]

    async def test_non_staging_turn_sends_the_agents_reply(
        self, repo: HistoryRepo
    ) -> None:
        question = "Happy to! How many dinners (3-4) and how many lunches?"
        transport = FakeTransport.scripted([ScriptedText(question)])
        handlers = BotHandlers(
            allowed_chat_id=CHAT_ID,
            session_factory=lambda chat_id: make_session(transport, repo),
        )
        bot = RecordingBot([])
        await handlers.on_text(
            fake_update(CHAT_ID, "plan my week"), SimpleNamespace(bot=bot)
        )

        assert bot.messages == [(question, None)]

    async def test_unauthorized_chat_is_refused_without_state_change(
        self, repo: HistoryRepo
    ) -> None:
        events: list[str] = []
        transport = FakeTransport.scripted(events=events)
        handlers = BotHandlers(
            allowed_chat_id=CHAT_ID,
            session_factory=lambda chat_id: make_session(transport, repo),
        )
        bot = RecordingBot(events)
        await handlers.on_text(fake_update(999, "hello"), SimpleNamespace(bot=bot))

        assert bot.messages == [(PRIVATE_BOT_TEXT, None)]
        assert "agent_call" not in events
        assert handlers.sessions == {}
