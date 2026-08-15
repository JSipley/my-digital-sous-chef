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
- **Button presses are a second entry point** and go through the same allowlist:
  callback queries carry an `effective_chat` and are authorized before any database
  read. The query is acknowledged first (to clear Telegram's loading spinner), then
  authorized.

## Commands

The bot is conversation-first (FR-001); commands are conveniences that inject the
equivalent natural-language turn into the same session.

| Command | Behavior |
|---|---|
| `/start` | Welcome + one-paragraph explanation of what the bot does and how to begin (supports SC-008 first-run guidance). Starts a session if none active. |
| `/plan` | Begins (or resumes) this week's planning conversation. |
| `/history` | Asks the agent to summarize past weeks from history (FR-024). |
| `/cookbook` | Opens the cookbook on the current week (FR-026a). **A deterministic database read and render — no agent turn, no typing indicator, instant reply.** This is a deliberate departure from `/plan` and `/history`, which both inject a conversational turn. |
| `/cancel` | Abandons the current session: in-memory state discarded, nothing logged (FR-021 edge case), confirmation message sent. |
| any text | Forwarded to the agent session as a conversational turn. |

### The cookbook surface (FR-026a)

One row per meal of the week's stored plan, in **`plan_json` order**, in one of three
states:

| State | Row | Button |
|---|---|---|
| Web recipe, no stored steps | `🔗 recipe: <url>` | none — the link is already inline |
| Stored steps | `📝 steps` (plus the link when it has one) | `📝 <meal>` — returns them instantly |
| Neither | `⏳ tap to write steps` | `⏳ <meal>` — authors and stores them, then returns them |

- Callback data is capped at 64 bytes by Telegram, so a meal tap encodes **week plus
  the meal's index into `plan_json`**, not its name. Rows and indices come from that
  same list; a name-ordered query would silently return the wrong meal.
- `← <week>` / `<week> →` walk to the nearest **accepted** week in each direction —
  weeks without a plan are skipped rather than offered as dead ends. Navigation
  **edits the existing message in place** so it reads as walking, not as new messages.
- Buttons in old messages stay live indefinitely. Every press re-reads the database,
  and a meal or week that no longer exists produces a short explanation, never a
  raised error.
- The ⏳ tap is the only press that waits on the agent: it shows the typing indicator,
  runs one turn to author and store the steps, then renders them from the database.

## Responsiveness (SC-007, FR-027)

- On every authorized incoming update the bot sends `sendChatAction("typing")`
  **before** invoking the agent; the action is refreshed every ~4 s until the reply is
  sent (Telegram expires it after ~5 s). No chat message is sent ahead of the reply.
- Contractual ordering asserted by test: `typing → agent call → reply`.

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
- **Instructions message**: sent as its own message when a cookbook row is tapped —
  `📝 <meal>`, then an `Ingredients` block with quantities, then numbered `Steps`.
  Ingredients are read from the stored plan; only the steps come from storage. Every
  line is MarkdownV2-escaped — authored prose and recipe URLs are full of reserved
  characters.
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

- **Loading**: typing indicator (above); no separate ack message.
- **Empty history** (first-ever session): no check-in prompt, no repetition rule;
  `/history` explains there are no past weeks yet.
- **Empty cookbook**: with no accepted plans at all, `/cookbook` explains that the
  cookbook fills in on first accept, mirroring the `/history` empty state. When only
  the *current* week is unaccepted, `/cookbook` still opens on it — headed with the
  current week, saying nothing is accepted for it yet, and offering `←` back to the
  most recent accepted week. It never silently retitles itself to an earlier week.
- **Zero lunches** (the default week, since lunches are never prompted for): the plan
  message still flags the batch meal, portioned for its dinner night only, and says so
  as plain coverage — `🍲 Batch meal — covers 1 dinner night (1 portion)` — not as a
  shortfall.
- **One dinner**: the plan message flags the single meal as the batch meal and carries
  no stretch-meal line; the agent says why (spec edge case).
