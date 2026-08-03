"""Integration tests for the cookbook (issue #3).

The whole story over one SQLite file: accepting a plan hands the agent an
instructions worklist, the agent saves steps, `/cookbook` renders them
without an agent turn, and tapping a row returns them. Plus the two
fallbacks — a meal that never got steps, and a recipe link the user says
is unusable.
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
from sous_chef.bot.app import (
    AGENT_FAILURE_TEXT,
    EMPTY_COOKBOOK_TEXT,
    STALE_BUTTON_TEXT,
    BotHandlers,
)
from sous_chef.bot.cookbook import MealTap, decode, encode_meal, encode_week
from sous_chef.bot.formatting import escape
from sous_chef.services.history_repo import HistoryRepo

CHAT_ID = 4242
WEEK = "2026-W31"
EARLIER_WEEK = "2026-W28"
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
CHILI_URL = "https://example.test/chicken-chili"


def meal(
    name: str,
    *,
    protein: str = "chicken",
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": protein,
        "prep_minutes": 30,
        "servings": 1,
        "batch": batch,
        "stretch": stretch,
        "source_url": source_url,
        "user_requested_repeat": False,
        "ingredients": [
            {
                "name": f"{protein} cut",
                "quantity": 2.0,
                "unit": "lb",
                "estimated_price_usd": 12.0,
            }
        ],
    }


def plan_payload(week_id: str = WEEK) -> dict[str, Any]:
    """Three meals: one with a recipe link, two needing instructions."""
    return {
        "week_id": week_id,
        "dinner_count": 3,
        "lunch_count": 2,
        "diet_type": None,
        "default_servings": 1,
        "weekly_budget_usd": None,
        "meals": [
            meal(
                "Zucchini boats",
                protein="turkey",
                batch={"lunches_covered": 2, "total_portions": 3},
            ),
            meal("Chicken chili", source_url=CHILI_URL),
            meal(
                "Braised short ribs",
                protein="beef",
                stretch={"technique": "braising"},
            ),
        ],
    }


SHORT_RIB_STEPS = ["Pat the ribs dry and season.", "Sear on all sides (5-6 min)."]


def save_call(
    meal_name: str, steps: list[str], week_id: str = WEEK
) -> ScriptedToolCall:
    return ScriptedToolCall(
        "save_meal_instructions",
        {"week_id": week_id, "meal_name": meal_name, "steps": steps},
    )


class RecordingBot:
    """Fake Telegram bot API, recording messages and keyboards."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.messages: list[tuple[str, str | None, Any]] = []

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        self.events.append(f"chat_action:{action}")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: Any = None,
    ) -> None:
        self.events.append(f"message:{text[:30]}")
        self.messages.append((text, parse_mode, reply_markup))

    @property
    def texts(self) -> list[str]:
        return [text for text, _, _ in self.messages]

    @property
    def last(self) -> tuple[str, str | None, Any]:
        return self.messages[-1]


class RecordingQuery:
    """The callback_query slice the handler uses."""

    def __init__(self, data: str | None) -> None:
        self.data = data
        self.answered = False
        self.edits: list[tuple[str, Any]] = []

    async def answer(self) -> None:
        self.answered = True

    async def edit_message_text(
        self, text: str, parse_mode: str | None = None, reply_markup: Any = None
    ) -> None:
        self.edits.append((text, reply_markup))


def text_update(chat_id: int, text: str) -> Any:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=SimpleNamespace(text=text),
        callback_query=None,
    )


def callback_update(chat_id: int, query: RecordingQuery) -> Any:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=None,
        callback_query=query,
    )


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepo:
    return HistoryRepo(tmp_path / "story5.db")


def handlers_for(
    transport: FakeTransport, repo: HistoryRepo, moment: datetime = NOW
) -> BotHandlers:
    return BotHandlers(
        allowed_chat_id=CHAT_ID,
        session_factory=lambda chat_id: Session(
            chat_id=chat_id,
            transport=transport,
            repo=repo,
            system_prompt=SYSTEM_PROMPT,
            tool_factory=build_tools,
            tz=UTC,
            now=lambda: moment,
        ),
    )


def accept_turn(*extra: Any) -> list[Any]:
    return [
        ScriptedToolCall("propose_plan", plan_payload()),
        ScriptedToolCall("accept_plan", {"week_id": WEEK}),
        *extra,
        ScriptedText("Your plan is set — grocery list below."),
    ]


class TestAcceptanceHandsOverAWorklist:
    async def test_accept_plan_lists_url_less_meals(self, repo: HistoryRepo) -> None:
        transport = FakeTransport.scripted(accept_turn())
        handlers = handlers_for(transport, repo)
        await handlers.on_text(text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx())

        accept = next(c for c in transport.tool_calls if c.name == "accept_plan")
        assert json.loads(accept.result)["instructions_needed"] == [
            "Zucchini boats",
            "Braised short ribs",
        ], "the meal with a recipe link is not on the worklist"


class TestCookbookScreen:
    async def test_empty_before_any_acceptance(self, repo: HistoryRepo) -> None:
        handlers = handlers_for(FakeTransport.scripted(), repo)
        bot = RecordingBot()
        await handlers.on_cookbook(text_update(CHAT_ID, "/cookbook"), ctx(bot))
        assert bot.texts == [EMPTY_COOKBOOK_TEXT]

    async def test_renders_three_states_without_an_agent_turn(
        self, repo: HistoryRepo
    ) -> None:
        events: list[str] = []
        transport = FakeTransport.scripted(
            accept_turn(save_call("Braised short ribs", SHORT_RIB_STEPS)),
            events=events,
        )
        handlers = handlers_for(transport, repo)
        await handlers.on_text(text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx())

        events.clear()
        bot = RecordingBot(events)
        await handlers.on_cookbook(text_update(CHAT_ID, "/cookbook"), ctx(bot))

        text, parse_mode, keyboard = bot.last
        assert parse_mode == "MarkdownV2"
        assert "this week" in text and escape(WEEK) in text
        assert "📝 steps" in text  # Braised short ribs
        assert "🔗 recipe" in text  # Chicken chili
        assert "⏳ tap to write steps" in text  # Zucchini boats
        assert "agent_call" not in events, "/cookbook is a pure database read"
        assert "chat_action:typing" not in events

        labels = [b.text for row in keyboard.inline_keyboard for b in row]
        assert labels == ["⏳ Zucchini boats", "📝 Braised short ribs"]

    async def test_opens_on_current_week_even_when_it_has_no_plan(
        self, repo: HistoryRepo
    ) -> None:
        earlier = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", plan_payload(EARLIER_WEEK)),
                ScriptedToolCall("accept_plan", {"week_id": EARLIER_WEEK}),
                ScriptedText("Done."),
            ]
        )
        past_moment = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
        await handlers_for(earlier, repo, past_moment).on_text(
            text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx()
        )

        handlers = handlers_for(FakeTransport.scripted(), repo)
        bot = RecordingBot()
        await handlers.on_cookbook(text_update(CHAT_ID, "/cookbook"), ctx(bot))

        text, _, keyboard = bot.last
        assert escape(WEEK) in text, "never silently retitles to an earlier week"
        assert "Nothing accepted for this week yet" in text
        assert [b.text for b in keyboard.inline_keyboard[0]] == [f"← {EARLIER_WEEK}"]


class TestTaps:
    async def test_stored_steps_return_instantly(self, repo: HistoryRepo) -> None:
        events: list[str] = []
        transport = FakeTransport.scripted(
            accept_turn(save_call("Braised short ribs", SHORT_RIB_STEPS)),
            events=events,
        )
        handlers = handlers_for(transport, repo)
        await handlers.on_text(text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx())

        events.clear()
        bot = RecordingBot(events)
        query = RecordingQuery(encode_meal(WEEK, 2))
        await handlers.on_callback(callback_update(CHAT_ID, query), ctx(bot))

        assert query.answered, "the spinner is cleared first"
        assert "agent_call" not in events, "stored steps need no agent turn"
        (text,) = bot.texts
        assert "Braised short ribs" in text
        assert text.index("Ingredients") < text.index("Steps")
        assert "beef cut" in text
        assert "1\\. Pat the ribs dry and season\\." in text

    async def test_hourglass_tap_generates_and_saves(self, repo: HistoryRepo) -> None:
        events: list[str] = []
        transport = FakeTransport.scripted(
            accept_turn(),
            # The turn the ⏳ tap drives.
            [
                save_call("Zucchini boats", ["Halve the zucchini.", "Bake 25 min."]),
                ScriptedText("Saved to your cookbook."),
            ],
            events=events,
        )
        handlers = handlers_for(transport, repo)
        await handlers.on_text(text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx())

        events.clear()
        bot = RecordingBot(events)
        query = RecordingQuery(encode_meal(WEEK, 0))
        await handlers.on_callback(callback_update(CHAT_ID, query), ctx(bot))

        assert "agent_call" in events, "the ⏳ tap is the one tap that waits"
        assert "chat_action:typing" in events
        (text,) = bot.texts
        assert "1\\. Halve the zucchini\\." in text
        assert repo.meal_instructions(WEEK, "Zucchini boats") is not None

        # The row is now 📝 and the next tap is instant.
        events.clear()
        bot2 = RecordingBot(events)
        await handlers.on_callback(
            callback_update(CHAT_ID, RecordingQuery(encode_meal(WEEK, 0))), ctx(bot2)
        )
        assert "agent_call" not in events

    async def test_hourglass_tap_falls_back_when_nothing_is_saved(
        self, repo: HistoryRepo
    ) -> None:
        """The agent chatted instead of tool-calling — say something, not nothing."""
        transport = FakeTransport.scripted(
            accept_turn(),
            [ScriptedText("Sure — brown the turkey, then bake the boats.")],
        )
        handlers = handlers_for(transport, repo)
        await handlers.on_text(text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx())

        bot = RecordingBot()
        await handlers.on_callback(
            callback_update(CHAT_ID, RecordingQuery(encode_meal(WEEK, 0))), ctx(bot)
        )
        assert bot.texts == ["Sure — brown the turkey, then bake the boats."]
        assert repo.meal_instructions(WEEK, "Zucchini boats") is None

    async def test_hourglass_tap_reports_an_agent_failure(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(accept_turn())  # script exhausted
        handlers = handlers_for(transport, repo)
        await handlers.on_text(text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx())

        bot = RecordingBot()
        await handlers.on_callback(
            callback_update(CHAT_ID, RecordingQuery(encode_meal(WEEK, 0))), ctx(bot)
        )
        assert bot.texts == [AGENT_FAILURE_TEXT], "a failed turn is never silent"

    async def test_week_navigation_edits_in_place(self, repo: HistoryRepo) -> None:
        for week_id, moment in (
            (EARLIER_WEEK, datetime(2026, 7, 8, 12, 0, tzinfo=UTC)),
            (WEEK, NOW),
        ):
            transport = FakeTransport.scripted(
                [
                    ScriptedToolCall("propose_plan", plan_payload(week_id)),
                    ScriptedToolCall("accept_plan", {"week_id": week_id}),
                    ScriptedText("Done."),
                ]
            )
            await handlers_for(transport, repo, moment).on_text(
                text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx()
            )

        handlers = handlers_for(FakeTransport.scripted(), repo)
        bot = RecordingBot()
        query = RecordingQuery(encode_week(EARLIER_WEEK))
        await handlers.on_callback(callback_update(CHAT_ID, query), ctx(bot))

        assert bot.messages == [], "navigation edits rather than sending a new message"
        (text, keyboard) = query.edits[0]
        assert escape(EARLIER_WEEK) in text and "this week" not in text
        assert [b.text for b in keyboard.inline_keyboard[-1]] == [f"{WEEK} →"]

    async def test_stale_button_is_tolerated(self, repo: HistoryRepo) -> None:
        transport = FakeTransport.scripted(accept_turn())
        handlers = handlers_for(transport, repo)
        await handlers.on_text(text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx())

        bot = RecordingBot()
        # An index past the end, and data this bot never produced.
        for data in (encode_meal(WEEK, 99), encode_meal("2020-W01", 0), "junk"):
            await handlers.on_callback(
                callback_update(CHAT_ID, RecordingQuery(data)), ctx(bot)
            )
        assert bot.texts == [STALE_BUTTON_TEXT] * 3

    async def test_unauthorized_callback_is_refused(self, repo: HistoryRepo) -> None:
        events: list[str] = []
        handlers = handlers_for(FakeTransport.scripted(events=events), repo)
        bot = RecordingBot(events)
        query = RecordingQuery(encode_meal(WEEK, 0))
        await handlers.on_callback(callback_update(999, query), ctx(bot))

        assert query.answered
        assert bot.texts == ["This is a private bot."]
        assert handlers.sessions == {}


class TestConversationalAccess:
    async def test_unusable_link_generates_and_saves_steps(
        self, repo: HistoryRepo
    ) -> None:
        """The only path that writes instructions for a meal with a URL."""
        transport = FakeTransport.scripted(
            accept_turn(),
            [
                ScriptedToolCall(
                    "get_meal_instructions", {"meal_name": "Chicken chili"}
                ),
                save_call("Chicken chili", ["Brown the chicken.", "Simmer 30 min."]),
                ScriptedText("Here you go — saved to your cookbook."),
            ],
        )
        handlers = handlers_for(transport, repo)
        await handlers.on_text(text_update(CHAT_ID, "3 dinners, 2 lunches"), ctx())
        await handlers.on_text(
            text_update(CHAT_ID, "that link's paywalled, just tell me"), ctx()
        )

        lookup = next(
            c for c in transport.tool_calls if c.name == "get_meal_instructions"
        )
        result = json.loads(lookup.result)
        assert result["ok"] is True
        assert result["instructions"] is None, "no steps yet, but the meal exists"
        assert result["source_url"] == CHILI_URL
        assert result["week_id"] == WEEK, "resolved without the agent supplying it"

        assert repo.meal_instructions(WEEK, "Chicken chili") is not None

        # The meal now has both a link and a button.
        bot = RecordingBot()
        await handlers.on_cookbook(text_update(CHAT_ID, "/cookbook"), ctx(bot))
        _, _, keyboard = bot.last
        labels = [b.text for row in keyboard.inline_keyboard for b in row]
        assert "📝 Chicken chili" in labels
        tap = decode(
            next(
                b.callback_data
                for row in keyboard.inline_keyboard
                for b in row
                if b.text == "📝 Chicken chili"
            )
        )
        assert isinstance(tap, MealTap)
        assert repo.plan_for_week(WEEK).meals[tap.index].name == "Chicken chili"


def ctx(bot: RecordingBot | None = None) -> Any:
    return SimpleNamespace(bot=bot if bot is not None else RecordingBot())
