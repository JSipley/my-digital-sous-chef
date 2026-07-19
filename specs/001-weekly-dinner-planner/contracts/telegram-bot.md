# Contract: Telegram Bot Surface

**Feature**: `001-weekly-dinner-planner` | **Date**: 2026-07-18

The user-facing interface is a Telegram bot connected by long polling. This contract
defines what the transport layer (`bot/`) guarantees, independent of what the agent
says. Integration tests exercise these guarantees through the handler layer with the
fake LLM transport.

## Access control

- Exactly one authorized user: incoming updates whose `chat_id` is not the configured
  `SOUS_CHEF_CHAT_ID` receive a single "this is a private bot" reply and are otherwise
  ignored. No agent call, no state change.

## Commands

The bot is conversation-first (FR-001); commands are conveniences that inject the
equivalent natural-language turn into the same session.

| Command | Behavior |
|---|---|
| `/start` | Welcome + one-paragraph explanation of what the bot does and how to begin (supports SC-008 first-run guidance). Starts a session if none active. |
| `/plan` | Begins (or resumes) this week's planning conversation. |
| `/history` | Asks the agent to summarize past weeks from history (FR-024). |
| `/cancel` | Abandons the current session: in-memory state discarded, nothing logged (FR-021 edge case), confirmation message sent. |
| any text | Forwarded to the agent session as a conversational turn. |

## Responsiveness (SC-007, FR-027)

- On every authorized incoming update the bot sends `sendChatAction("typing")`
  **before** invoking the agent; the action is refreshed every ~4 s until the reply is
  sent (Telegram expires it after ~5 s).
- For turns that trigger plan generation, a short acknowledgment message is sent
  immediately, before the agent call ("On it — pulling your plan together…").
- Contractual ordering asserted by test: `ack/typing → agent call → reply`.

## Message formatting (FR-026)

All output rendered by `bot/formatting.py` in Telegram **MarkdownV2** with reserved
characters escaped. Phone-readability rules:

- **Plan message**: one meal per block — name (bold), flags on their own line
  (`🍲 Batch meal — covers 3 lunches + 1 dinner (4 portions)` /
  `✨ Stretch meal — new technique: braising`), then `⏱ prep`, `🍽 servings`,
  `🥩 protein`, and `🔗 source` when a web recipe backs the meal. Open nights listed
  at the end.
- **Grocery list message**: sent as its own message so it can be scrolled while
  shopping; one item per line, `• name — quantity (est. $x.xx)`; final line
  `Estimated bill: $XX.XX`, plus `(budget $YY — under/over by $Z)` when a budget is
  set. Items and totals come verbatim from the `accept_plan` result — the transport
  never recomputes or reorders them.
- Messages exceeding Telegram's 4096-char limit are split at line boundaries, never
  mid-item.

## Error states (FR-028, constitution Principle III)

Every user-visible error states what happened and what to do next:

| Condition | User-visible behavior |
|---|---|
| Agent/API failure (timeout, 5xx, refusal) | "I hit a problem generating that — nothing was saved. Try again, or /cancel to start over." Session state kept so the turn can be retried. |
| Constraint conflict (agent cannot satisfy all constraints) | Agent-authored message naming the failed constraint and the user's options (relax budget, allow a repeat…) — never an empty reply. |
| Unauthorized chat | Single refusal message, no state change. |
| Telegram delivery failure | Retried by the framework; logged; no duplicate side effects (accept_plan is idempotent per week upsert). |

## Loading / empty states

- **Loading**: typing indicator + ack message (above).
- **Empty history** (first-ever session): no check-in prompt, no repetition rule;
  `/history` explains there are no past weeks yet.
- **Zero lunches**: plan message still flags the batch meal, portioned for its dinner
  night only, and notes the reduced meal-prep benefit (spec edge case).
