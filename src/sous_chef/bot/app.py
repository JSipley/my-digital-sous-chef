"""Telegram transport per contracts/telegram-bot.md.

Long polling, single-chat allowlist, command handlers, and delivery of the
agent's replies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from sous_chef.agent.session import Session
from sous_chef.bot.ack import PLAN_ACK_TEXT, WorkingIndicator, looks_like_plan_request
from sous_chef.bot.formatting import render_plan

PRIVATE_BOT_TEXT = "This is a private bot."
WELCOME_TEXT = (
    "Hi! I'm your digital sous chef. Each week, tell me how many dinners (3-4) "
    "and how many lunches you want to cook, and I'll put together a plan of "
    "healthy, high-protein meals — including one big-batch dish that covers your "
    "lunches and one stretch meal that teaches you a new technique. You can swap "
    "meals, set a budget, or change preferences at any point, and when you accept "
    "the plan you'll get a grocery list with an estimated bill. "
    "Just tell me your dinner and lunch counts to begin."
)
CANCEL_TEXT = (
    "Session abandoned — nothing was saved. Send a message any time to start fresh."
)
PLAN_COMMAND_TURN = "Let's plan this week's dinners and lunches."
HISTORY_COMMAND_TURN = "What have I cooked in past weeks?"

SessionFactory = Callable[[int], Session]
SendMessage = Callable[..., Awaitable[object]]


class BotHandlers:
    """Update handlers, decoupled from the Application for testability."""

    def __init__(
        self, *, allowed_chat_id: int, session_factory: SessionFactory
    ) -> None:
        self._allowed_chat_id = allowed_chat_id
        self._session_factory = session_factory
        self.sessions: dict[int, Session] = {}

    def session_for(self, chat_id: int) -> Session:
        if chat_id not in self.sessions:
            self.sessions[chat_id] = self._session_factory(chat_id)
        return self.sessions[chat_id]

    async def on_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        chat_id = await self._authorized_chat_id(update, context)
        if chat_id is None:
            return
        self.session_for(chat_id)
        await context.bot.send_message(chat_id, WELCOME_TEXT)

    async def on_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = await self._authorized_chat_id(update, context)
        if chat_id is None:
            return
        await self._run_turn(chat_id, context, PLAN_COMMAND_TURN)

    async def on_history(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        chat_id = await self._authorized_chat_id(update, context)
        if chat_id is None:
            return
        await self._run_turn(chat_id, context, HISTORY_COMMAND_TURN)

    async def on_cancel(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        chat_id = await self._authorized_chat_id(update, context)
        if chat_id is None:
            return
        self.sessions.pop(chat_id, None)
        await context.bot.send_message(chat_id, CANCEL_TEXT)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = await self._authorized_chat_id(update, context)
        if chat_id is None:
            return
        message = update.effective_message
        if message is None or message.text is None:
            return
        await self._run_turn(chat_id, context, message.text)

    async def _run_turn(
        self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> None:
        session = self.session_for(chat_id)
        ack_text = PLAN_ACK_TEXT if looks_like_plan_request(text) else None
        async with WorkingIndicator(context.bot, chat_id, ack_text=ack_text):
            outcome = await session.handle_message(text)
        if outcome.reply_text:
            await context.bot.send_message(chat_id, outcome.reply_text)
        if outcome.newly_staged_plan is not None:
            await context.bot.send_message(
                chat_id,
                render_plan(outcome.newly_staged_plan),
                parse_mode="MarkdownV2",
            )

    async def _authorized_chat_id(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int | None:
        chat = update.effective_chat
        if chat is None:
            return None
        if chat.id != self._allowed_chat_id:
            await context.bot.send_message(chat.id, PRIVATE_BOT_TEXT)
            return None
        return chat.id


def build_application(token: str, handlers: BotHandlers) -> Application:
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", handlers.on_start))
    application.add_handler(CommandHandler("plan", handlers.on_plan))
    application.add_handler(CommandHandler("history", handlers.on_history))
    application.add_handler(CommandHandler("cancel", handlers.on_cancel))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text)
    )
    return application
