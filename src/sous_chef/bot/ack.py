"""Typing indicator while the agent works (SC-007, FR-027).

Telegram expires a chat action after ~5 s, so the typing indicator is
refreshed every ~4 s for as long as the agent is working.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Protocol

TYPING_REFRESH_SECONDS = 4.0


class ChatActions(Protocol):
    """The slice of the Telegram bot API the indicator needs."""

    async def send_chat_action(self, chat_id: int, action: str) -> object: ...


class WorkingIndicator:
    """Typing indicator before the agent call, refreshed until the reply is sent."""

    def __init__(self, bot: ChatActions, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._refresh_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> WorkingIndicator:
        await self._bot.send_chat_action(self._chat_id, "typing")
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
