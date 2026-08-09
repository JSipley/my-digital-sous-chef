"""Entry point: python -m sous_chef."""

from __future__ import annotations

import logging
import os

from sous_chef.agent.client import AnthropicTransport
from sous_chef.agent.prompt import SYSTEM_PROMPT
from sous_chef.agent.session import Session
from sous_chef.agent.tools import build_tools
from sous_chef.bot.app import BotHandlers, build_application
from sous_chef.config import Settings
from sous_chef.services.history_repo import HistoryRepo


def main() -> None:
    # Without this the root logger is unconfigured: our own logger.exception
    # calls fall back to logging.lastResort (no timestamp, no level, no logger
    # name) and python-telegram-bot's diagnostics are dropped entirely.
    logging.basicConfig(
        level=os.environ.get("SOUS_CHEF_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO, and Telegram's API embeds the bot
    # token in every path — that would write the token to the log on every poll.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = Settings.from_env()
    repo = HistoryRepo(settings.db_path)
    transport = AnthropicTransport(settings)

    def session_factory(chat_id: int) -> Session:
        return Session(
            chat_id=chat_id,
            transport=transport,
            repo=repo,
            system_prompt=SYSTEM_PROMPT,
            tool_factory=build_tools,
            tz=settings.tz,
        )

    handlers = BotHandlers(
        allowed_chat_id=settings.chat_id, session_factory=session_factory
    )
    application = build_application(settings.telegram_token, handlers)
    application.run_polling()


if __name__ == "__main__":
    main()
