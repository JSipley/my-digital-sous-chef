"""Telegram transport per contracts/telegram-bot.md.

Long polling, single-chat allowlist, command handlers, delivery of the
agent's replies, and the user-visible error states (FR-028).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from telegram import InlineKeyboardMarkup, Update
from telegram.error import BadRequest, NetworkError, RetryAfter
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from sous_chef.agent.session import Session
from sous_chef.bot.ack import WorkingIndicator
from sous_chef.bot.cookbook import MealTap, WeekNav, build_keyboard, decode
from sous_chef.bot.formatting import (
    render_cookbook,
    render_cookbook_empty_week,
    render_grocery_list,
    render_instructions,
    render_plan,
)

PRIVATE_BOT_TEXT = "This is a private bot."
WELCOME_TEXT = (
    "Hi! I'm your digital sous chef. Each week, tell me how many dinners (1-7) "
    "you want to cook, and I'll put together a plan of healthy, high-protein "
    "meals — including one big-batch dish and one stretch meal that teaches you "
    "a new technique. Want lunches covered too? Say how many and the batch dish "
    "will cover them. You can swap meals, set a budget, or change preferences at "
    "any point, and when you accept the plan you'll get a grocery list with an "
    "estimated bill. Just tell me your dinner count to begin."
)
CANCEL_TEXT = (
    "Session abandoned — nothing was saved. Send a message any time to start fresh."
)
PLAN_COMMAND_TURN = "Let's plan this week's dinners."
HISTORY_COMMAND_TURN = "What have I cooked in past weeks?"
AGENT_FAILURE_TEXT = (
    "I hit a problem generating that — nothing was saved. "
    "Try again, or /cancel to start over."
)
EMPTY_HISTORY_TEXT = (
    "There are no past weeks yet — history starts once you accept your "
    "first plan. Tell me how many dinners you want to plan one."
)
EMPTY_COOKBOOK_TEXT = (
    "Your cookbook is empty — it fills up when you accept your first plan. "
    "Every meal then gets either a recipe link or step-by-step instructions "
    "you can pull up here. Tell me how many dinners you want to plan one."
)
STALE_BUTTON_TEXT = (
    "That meal is no longer in your cookbook. Send /cookbook for the current week."
)


def _instructions_turn(meal_name: str, week_id: str) -> str:
    return (
        f"Write the step-by-step cooking instructions for {meal_name} in week "
        f"{week_id} and save them with save_meal_instructions."
    )


SessionFactory = Callable[[int], Session]

logger = logging.getLogger(__name__)


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
        if not self.session_for(chat_id).repo.has_any_plans():
            await context.bot.send_message(chat_id, EMPTY_HISTORY_TEXT)
            return
        await self._run_turn(chat_id, context, HISTORY_COMMAND_TURN)

    async def on_cookbook(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        chat_id = await self._authorized_chat_id(update, context)
        if chat_id is None:
            return
        session = self.session_for(chat_id)
        if not session.repo.has_any_plans():
            await context.bot.send_message(chat_id, EMPTY_COOKBOOK_TEXT)
            return
        # Always opens on the current week, even when it has no plan yet —
        # the ← button then walks back to the most recent accepted one.
        text, keyboard = self._cookbook_screen(session, session.current_week_id())
        await context.bot.send_message(
            chat_id, text, parse_mode="MarkdownV2", reply_markup=keyboard
        )

    def _cookbook_screen(
        self, session: Session, week_id: str
    ) -> tuple[str, InlineKeyboardMarkup | None]:
        """The rendered cookbook for one week: a pure database read."""
        plan = session.repo.plan_for_week(week_id)
        instructions = session.repo.instructions_for_week(week_id)
        if plan is None:
            text = render_cookbook_empty_week(
                week_id, is_current_week=week_id == session.current_week_id()
            )
        else:
            text = render_cookbook(
                week_id,
                plan,
                instructions,
                is_current_week=week_id == session.current_week_id(),
            )
        keyboard = build_keyboard(
            week_id,
            plan,
            instructions,
            previous_week=session.repo.previous_accepted_week(week_id),
            next_week=session.repo.next_accepted_week(week_id),
        )
        return text, keyboard

    async def on_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None:
            return
        # Clear Telegram's spinner before anything else can fail.
        await query.answer()
        chat_id = await self._authorized_chat_id(update, context)
        if chat_id is None:
            return
        action = decode(query.data)
        if action is None:
            await context.bot.send_message(chat_id, STALE_BUTTON_TEXT)
            return
        session = self.session_for(chat_id)
        if isinstance(action, WeekNav):
            text, keyboard = self._cookbook_screen(session, action.week_id)
            # Edit in place so ←/→ walks the history instead of spamming.
            await query.edit_message_text(
                text, parse_mode="MarkdownV2", reply_markup=keyboard
            )
            return
        await self._send_meal_instructions(chat_id, context, session, action)

    async def _send_meal_instructions(
        self,
        chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        session: Session,
        tap: MealTap,
    ) -> None:
        # Every press re-reads the database: buttons in old messages stay
        # live, and the meal behind one may since have gone away.
        plan = session.repo.plan_for_week(tap.week_id)
        if plan is None or tap.index >= len(plan.meals):
            await context.bot.send_message(chat_id, STALE_BUTTON_TEXT)
            return
        meal = plan.meals[tap.index]
        instructions = session.repo.meal_instructions(tap.week_id, meal.name)
        if instructions is None:
            # The ⏳ state: the only tap that waits on the agent.
            instructions = await self._generate_instructions(
                chat_id, context, session, meal.name, tap.week_id
            )
            if instructions is None:
                return
        for chunk in render_instructions(meal, instructions):
            await context.bot.send_message(chat_id, chunk, parse_mode="MarkdownV2")

    async def _generate_instructions(
        self,
        chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        session: Session,
        meal_name: str,
        week_id: str,
    ) -> str | None:
        """Run one agent turn to write and save steps; None if it failed."""
        try:
            async with WorkingIndicator(context.bot, chat_id):
                outcome = await session.handle_message(
                    _instructions_turn(meal_name, week_id)
                )
        except Exception:
            logger.exception("instructions turn failed for chat %s", chat_id)
            await context.bot.send_message(chat_id, AGENT_FAILURE_TEXT)
            return None
        saved = session.repo.meal_instructions(week_id, meal_name)
        if saved is None:
            # The agent answered without saving — deliver what it said
            # rather than nothing.
            await context.bot.send_message(
                chat_id, outcome.reply_text or AGENT_FAILURE_TEXT
            )
        return saved

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
        try:
            async with WorkingIndicator(context.bot, chat_id):
                outcome = await session.handle_message(text)
        except Exception:
            # Session state is kept so the turn can simply be retried;
            # nothing reaches SQLite outside a completed accept_plan.
            logger.exception("agent turn failed for chat %s", chat_id)
            await context.bot.send_message(chat_id, AGENT_FAILURE_TEXT)
            return
        if outcome.newly_staged_plan is not None:
            # The rendered plan replaces the agent's reply text for this
            # turn: both describe the same plan, and only one of them is
            # formatted for a phone.
            await context.bot.send_message(
                chat_id,
                render_plan(outcome.newly_staged_plan),
                parse_mode="MarkdownV2",
            )
        elif outcome.reply_text:
            await context.bot.send_message(chat_id, outcome.reply_text)
        if outcome.newly_accepted is not None:
            chunks = render_grocery_list(
                outcome.newly_accepted.grocery,
                outcome.newly_accepted.plan.weekly_budget_usd,
            )
            for chunk in chunks:
                await context.bot.send_message(chat_id, chunk, parse_mode="MarkdownV2")

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


async def on_error(_update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the errors python-telegram-bot routes here.

    Polling runs under PTB's `network_retry_loop` with `max_retries=-1`, so a
    connectivity error there is retried until it succeeds. A traceback for one
    is indistinguishable in the log from a bot that has actually stopped, so
    those are logged as a single line instead.
    """
    error = context.error
    # BadRequest subclasses NetworkError, but it means our own MarkdownV2 is
    # malformed: nothing retries it and it must keep its traceback.
    if isinstance(error, NetworkError | RetryAfter) and not isinstance(
        error, BadRequest
    ):
        logger.warning("transient Telegram network error, retrying: %s", error)
        return
    logger.error("unhandled error while processing an update", exc_info=error)


def build_application(token: str, handlers: BotHandlers) -> Application:
    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", handlers.on_start))
    application.add_handler(CommandHandler("plan", handlers.on_plan))
    application.add_handler(CommandHandler("history", handlers.on_history))
    application.add_handler(CommandHandler("cookbook", handlers.on_cookbook))
    application.add_handler(CommandHandler("cancel", handlers.on_cancel))
    application.add_handler(CallbackQueryHandler(handlers.on_callback))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text)
    )
    application.add_error_handler(on_error)
    return application
