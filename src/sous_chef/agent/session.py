"""In-memory per-chat session state and message loop (FR-021).

A Session lives only in memory: abandoning it (process restart, /cancel,
user silence) discards the object and nothing reaches SQLite until the
agent calls accept_plan.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from anthropic.lib.tools import BetaAsyncFunctionTool

from sous_chef.agent.client import MessageHistory, Transport
from sous_chef.models.history import CheckinResult
from sous_chef.models.plan import WeeklyPlan
from sous_chef.services.history_repo import HistoryRepo


@dataclass
class SessionState:
    """Everything the current planning conversation knows; never persisted."""

    chat_id: int
    messages: MessageHistory = field(default_factory=list)
    dinner_count: int | None = None
    lunch_count: int | None = None
    diet_type: str | None = None
    default_servings: int = 1
    weekly_budget_usd: float | None = None
    staged_draft: WeeklyPlan | None = None
    repetition_relaxed: bool = False
    pending_checkin: CheckinResult | None = None


@dataclass(frozen=True)
class TurnOutcome:
    """What the bot should deliver after one conversational turn."""

    reply_text: str
    newly_staged_plan: WeeklyPlan | None


ToolFactory = Callable[["Session"], Sequence[BetaAsyncFunctionTool[Any]]]


def _no_tools(_session: Session) -> Sequence[BetaAsyncFunctionTool[Any]]:
    return ()


class Session:
    """One chat's conversation loop over the transport and the session's tools."""

    def __init__(
        self,
        *,
        chat_id: int,
        transport: Transport,
        repo: HistoryRepo,
        system_prompt: str,
        tool_factory: ToolFactory = _no_tools,
    ) -> None:
        self.state = SessionState(chat_id=chat_id)
        self.repo = repo
        self._transport = transport
        self._system_prompt = system_prompt
        self._tools = tool_factory(self)

    async def handle_message(self, text: str) -> TurnOutcome:
        self.state.messages.append({"role": "user", "content": text})
        draft_before = self.state.staged_draft
        result = await self._transport.run_turn(
            system=self._system_prompt,
            tools=self._tools,
            messages=self.state.messages,
        )
        draft_after = self.state.staged_draft
        return TurnOutcome(
            reply_text=result.text,
            newly_staged_plan=draft_after if draft_after is not draft_before else None,
        )

    def stage_draft(self, plan: WeeklyPlan) -> None:
        """Record a validated draft (from propose_plan) and mirror its config."""
        self.state.staged_draft = plan
        self.state.dinner_count = plan.dinner_count
        self.state.lunch_count = plan.lunch_count
        self.state.diet_type = plan.diet_type
        self.state.default_servings = plan.default_servings
        self.state.weekly_budget_usd = plan.weekly_budget_usd
