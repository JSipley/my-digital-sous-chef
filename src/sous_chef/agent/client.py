"""Anthropic client transport: beta tool runner + pause_turn handling (R4/R6).

The `Transport` protocol is the seam the integration tests fake: it runs one
full agentic turn (model ↔ tools until the model stops calling tools) against
a mutable message history and returns the user-visible reply text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx
from anthropic import AsyncAnthropic
from anthropic.lib.tools import BetaAsyncFunctionTool
from anthropic.types.beta import BetaMessageParam, BetaToolUnionParam

from sous_chef.config import Settings

MessageHistory = list[dict[str, Any]]
"""Session conversation history, mutated in place by run_turn."""

MAX_PAUSE_TURN_RESTARTS = 5
MAX_TOKENS = 8192

# The SDK default read timeout is 10 minutes, and PTB processes updates
# sequentially — so a connection that goes silent mid-stream (dropped wifi,
# black-holed route) wedges the one bot chat for up to ~30 min across
# retries (issue #9), rather than failing into AGENT_FAILURE_TEXT. httpx's
# read timeout only measures the gap between chunks, not total stream
# duration, so a lower value is safe for slow-but-alive generations.
REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

SERVER_TOOLS: list[BetaToolUnionParam] = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
]


@dataclass(frozen=True)
class TurnResult:
    """The user-visible outcome of one agentic turn."""

    text: str


class Transport(Protocol):
    """Runs one agentic turn; implemented by AnthropicTransport and the test fake."""

    async def run_turn(
        self,
        *,
        system: str,
        tools: Sequence[BetaAsyncFunctionTool[Any]],
        messages: MessageHistory,
    ) -> TurnResult: ...


class AnthropicTransport:
    """Real Claude API transport: streaming runner, caching, pause_turn restarts."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key, timeout=REQUEST_TIMEOUT
        )
        self._model = settings.model

    async def run_turn(
        self,
        *,
        system: str,
        tools: Sequence[BetaAsyncFunctionTool[Any]],
        messages: MessageHistory,
    ) -> TurnResult:
        texts: list[str] = []
        restarts = 0
        while True:
            last_stop_reason = await self._run_runner(
                system=system, tools=tools, messages=messages, texts=texts
            )
            if last_stop_reason == "pause_turn" and restarts < MAX_PAUSE_TURN_RESTARTS:
                restarts += 1
                continue
            break
        return TurnResult(text="\n\n".join(texts))

    async def _run_runner(
        self,
        *,
        system: str,
        tools: Sequence[BetaAsyncFunctionTool[Any]],
        messages: MessageHistory,
        texts: list[str],
    ) -> str | None:
        runner = self._client.beta.messages.tool_runner(
            model=self._model,
            max_tokens=MAX_TOKENS,
            # The stable prefix (tools, then system) carries the single cache
            # breakpoint; per-turn content only ever appears in messages (R12).
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[*tools, *SERVER_TOOLS],
            messages=cast("list[BetaMessageParam]", messages),
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            stream=True,
        )
        stop_reason: str | None = None
        async for stream in runner:
            message = await stream.get_final_message()
            stop_reason = message.stop_reason
            texts.extend(
                block.text
                for block in message.content
                if block.type == "text" and block.text
            )
            messages.append({"role": "assistant", "content": message.content})
            tool_response = await runner.generate_tool_call_response()
            if tool_response is not None:
                messages.append(cast("dict[str, Any]", tool_response))
        return stop_reason
