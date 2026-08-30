"""Live-API smoke tests — marked `live`, excluded from the default run.

Run with: uv run pytest -m live  (requires ANTHROPIC_API_KEY)
Draft-plan latency budget: uv run pytest -m live -k draft_latency
"""

import os
import time
from pathlib import Path

import pytest

from sous_chef.agent.client import AnthropicTransport
from sous_chef.agent.prompt import SYSTEM_PROMPT
from sous_chef.agent.session import Session
from sous_chef.agent.tools import build_tools
from sous_chef.config import Settings
from sous_chef.services.history_repo import HistoryRepo

DRAFT_LATENCY_BUDGET_SECONDS = 30.0

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="live tests need ANTHROPIC_API_KEY",
    ),
]


@pytest.fixture
def live_session(tmp_path: Path) -> Session:
    settings = Settings.from_env(
        {
            "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
            "SOUS_CHEF_TELEGRAM_TOKEN": "live-smoke-unused",
            "SOUS_CHEF_CHAT_ID": "1",
            "SOUS_CHEF_DB_PATH": str(tmp_path / "live.db"),
        }
    )
    return Session(
        chat_id=1,
        transport=AnthropicTransport(settings),
        repo=HistoryRepo(settings.db_path),
        system_prompt=SYSTEM_PROMPT,
        tool_factory=build_tools,
        tz=settings.tz,
    )


class TestLiveSmoke:
    async def test_end_to_end_plan_generation(self, live_session: Session) -> None:
        outcome = await live_session.handle_message(
            "I want to cook 3 dinners and 2 lunches this week. "
            "Propose the plan right away."
        )
        assert outcome.reply_text.strip(), "the agent must reply with text"
        plan = outcome.newly_staged_plan
        assert plan is not None, "a counts-only request must stage a draft plan"
        assert plan.dinner_count == 3
        assert plan.lunch_count == 2
        assert plan.batch_meal is not None
        assert plan.stretch_meal is not None

    async def test_draft_latency_under_budget(self, live_session: Session) -> None:
        started = time.perf_counter()
        outcome = await live_session.handle_message(
            "3 dinners and 2 lunches this week — propose the plan right away."
        )
        elapsed = time.perf_counter() - started
        assert outcome.newly_staged_plan is not None
        assert elapsed < DRAFT_LATENCY_BUDGET_SECONDS, (
            f"draft plan took {elapsed:.1f}s; budget is "
            f"{DRAFT_LATENCY_BUDGET_SECONDS:.0f}s"
        )
