"""Immediate acknowledgment and typing indicator (SC-007, FR-027).

Telegram expires a chat action after ~5 s, so the typing indicator is
refreshed every ~4 s for as long as the agent is working.
"""

from __future__ import annotations

import asyncio
import re
from types import TracebackType
from typing import Protocol

TYPING_REFRESH_SECONDS = 4.0
PLAN_ACK_TEXT = "On it — pulling your plan together…"

_PLAN_INTENT = re.compile(r"\d|\bplan\b|\bdinners?\b|\blunch(es)?\b", re.IGNORECASE)


class ChatActions(Protocol):
    """The slice of the Telegram bot API the indicator needs."""

    async def send_chat_action(self, chat_id: int, action: str) -> object: ...

    async def send_message(self, chat_id: int, text: str) -> object: ...


def looks_like_plan_request(text: str) -> bool:
    """Heuristic for turns that trigger plan generation and deserve an ack."""
    return bool(_PLAN_INTENT.search(text))


class WorkingIndicator:
    """Ack + typing before the agent call, refreshed until the reply is sent."""

    def __init__(
        self,
        bot: ChatActions,
        chat_id: int,
        *,
        ack_text: str | None = None,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._ack_text = ack_text
        self._refresh_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> WorkingIndicator:
        await self._bot.send_chat_action(self._chat_id, "typing")
        if self._ack_text is not None:
            await self._bot.send_message(self._chat_id, self._ack_text)
        self._refresh_task = asyncio.create_task(self._keep_typing())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()

    async def _keep_typing(self) -> None:
        while True:
            await asyncio.sleep(TYPING_REFRESH_SECONDS)
            await self._bot.send_chat_action(self._chat_id, "typing")
