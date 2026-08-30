"""Scripted fake LLM transport.

Implements the same `Transport` protocol as `agent/client.py` but replays
scripted turns deterministically offline. Tool calls in the script are
executed against the real client tools, so integration tests drive the real
session loop, tools, services, and SQLite with zero network.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sous_chef.agent.client import MessageHistory, TurnResult


@dataclass(frozen=True)
class ScriptedToolCall:
    """The model 'decides' to call a client tool with this exact input."""

    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ScriptedText:
    """The model 'writes' this text."""

    text: str


Step = ScriptedToolCall | ScriptedText
Turn = list[Step]


@dataclass
class ToolCallRecord:
    name: str
    input: dict[str, Any]
    result: str


@dataclass
class FakeTransport:
    """Replays one scripted turn per run_turn call, executing real tools."""

    turns: deque[Turn]
    events: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    @classmethod
    def scripted(cls, *turns: Turn, events: list[str] | None = None) -> FakeTransport:
        return cls(turns=deque(turns), events=events if events is not None else [])

    async def run_turn(
        self,
        *,
        system: str,
        tools: Sequence[Any],
        messages: MessageHistory,
    ) -> TurnResult:
        assert system, "run_turn must receive a non-empty system prompt"
        self.events.append("agent_call")
        assert self.turns, "FakeTransport script exhausted: unexpected extra turn"
        turn = self.turns.popleft()
        by_name = {tool.name: tool for tool in tools}
        texts: list[str] = []
        for step in turn:
            if isinstance(step, ScriptedText):
                texts.append(step.text)
                continue
            tool = by_name[step.name]
            result = await tool.call(step.input)
            assert isinstance(result, str)
            self.tool_calls.append(ToolCallRecord(step.name, step.input, result))
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"toolu_{len(self.tool_calls)}",
                            "name": step.name,
                            "input": step.input,
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"toolu_{len(self.tool_calls)}",
                            "content": result,
                        }
                    ],
                }
            )
        text = "\n\n".join(texts)
        messages.append({"role": "assistant", "content": text})
        return TurnResult(text=text)
