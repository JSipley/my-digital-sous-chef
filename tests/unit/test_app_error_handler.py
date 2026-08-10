"""Unit test for dispatcher-level error handling (issue #9).

Without a registered error handler, PTB logs polling/dispatcher errors as
"No error handlers are registered, logging exception" — indistinguishable
in the log from an unhandled crash even though PTB's own retry loop already
recovers. build_application must register one.
"""

from sous_chef.bot.app import BotHandlers, build_application


def test_build_application_registers_an_error_handler() -> None:
    handlers = BotHandlers(allowed_chat_id=1, session_factory=lambda chat_id: None)  # type: ignore[arg-type]
    application = build_application("123:test-token", handlers)
    assert application.error_handlers
