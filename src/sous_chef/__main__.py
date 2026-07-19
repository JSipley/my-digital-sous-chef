"""Entry point: python -m sous_chef."""

from __future__ import annotations

from sous_chef.agent.client import AnthropicTransport
from sous_chef.agent.session import Session
from sous_chef.bot.app import BotHandlers, build_application
from sous_chef.config import Settings
from sous_chef.services.history_repo import HistoryRepo

PLACEHOLDER_SYSTEM_PROMPT = (
    "You are a helpful meal-planning assistant. Full planning behavior arrives "
    "with the propose_plan tooling."
)


def main() -> None:
    settings = Settings.from_env()
    repo = HistoryRepo(settings.db_path)
    transport = AnthropicTransport(settings)

    def session_factory(chat_id: int) -> Session:
        return Session(
            chat_id=chat_id,
            transport=transport,
            repo=repo,
            system_prompt=PLACEHOLDER_SYSTEM_PROMPT,
        )

    handlers = BotHandlers(
        allowed_chat_id=settings.chat_id, session_factory=session_factory
    )
    application = build_application(settings.telegram_token, handlers)
    application.run_polling()


if __name__ == "__main__":
    main()
