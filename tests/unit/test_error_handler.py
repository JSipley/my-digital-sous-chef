"""Unit tests for the bot's Telegram error handler (issue #20).

With no handler registered, python-telegram-bot logged a full traceback at
ERROR for connectivity blips its own retry loop recovers from, which reads
exactly like a dead bot. The trap this file exists to prevent: `BadRequest`
subclasses `NetworkError`, so a naive isinstance check would also silence
MarkdownV2 formatting bugs, which are ours and never self-heal.
"""

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from telegram.error import (
    BadRequest,
    Conflict,
    Forbidden,
    NetworkError,
    RetryAfter,
    TimedOut,
)

from sous_chef.bot.app import BotHandlers, build_application, on_error

LOGGER_NAME = "sous_chef.bot.app"


def context_for(error: BaseException | None) -> Any:
    """The only attribute the error handler reads off the context."""
    return SimpleNamespace(error=error)


async def test_network_error_logs_one_warning_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = NetworkError(
        "httpx.ConnectError: [Errno -3] Temporary failure in name resolution"
    )
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        await on_error(None, context_for(error))

    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert "Temporary failure in name resolution" in record.getMessage()


async def test_timed_out_and_retry_after_are_also_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        await on_error(None, context_for(TimedOut()))
        await on_error(None, context_for(RetryAfter(30)))

    assert [record.levelno for record in caplog.records] == [
        logging.WARNING,
        logging.WARNING,
    ]
    assert all(record.exc_info is None for record in caplog.records)


async def test_bad_request_stays_an_error_with_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # BadRequest subclasses NetworkError but means our own MarkdownV2 is
    # broken: it never recovers on its own and must keep its traceback.
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        await on_error(None, context_for(BadRequest("Can't parse entities")))

    (record,) = caplog.records
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


async def test_other_errors_stay_errors_with_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        await on_error(None, context_for(Conflict("terminated by other getUpdates")))
        await on_error(None, context_for(Forbidden("bot was blocked by the user")))
        await on_error(None, context_for(RuntimeError("something else entirely")))

    assert [record.levelno for record in caplog.records] == [logging.ERROR] * 3
    assert all(record.exc_info is not None for record in caplog.records)


async def test_missing_error_is_still_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # context.error is optional; a None must not be silently dropped.
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        await on_error(None, context_for(None))

    (record,) = caplog.records
    assert record.levelno == logging.ERROR


def built_application() -> Any:
    handlers = BotHandlers(allowed_chat_id=1, session_factory=lambda _chat_id: None)
    return build_application("123456:test-token", handlers)


def test_build_application_registers_the_error_handler() -> None:
    assert on_error in built_application().error_handlers


async def test_application_routes_polling_errors_to_the_handler(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The wiring, not just the function.

    `run_polling` forwards every polling error through `process_error`. This
    is the path that used to emit PTB's "No error handlers are registered"
    fallback, and it is the one the fix has to land on.
    """
    application = built_application()
    error = NetworkError(
        "httpx.ConnectError: [Errno -3] Temporary failure in name resolution"
    )
    with caplog.at_level(logging.DEBUG):
        await application.process_error(update=None, error=error)

    assert not any(
        "No error handlers are registered" in record.getMessage()
        for record in caplog.records
    )
    (record,) = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
