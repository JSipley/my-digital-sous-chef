# My Digital Sous Chef

A single-user, conversational weekly dinner planner delivered as a **Telegram
bot**. Tell it how many dinners (3–4) and lunches you want to cook this week
and it curates healthy, high-protein meals — always exactly one **batch meal**
(cooked once, portioned to cover your lunches) and one **stretch meal** that
teaches a new technique. Accepting the plan produces a merged **grocery list**
with a computed **estimated bill**, optionally checked against a weekly
budget. Accepted plans persist to SQLite; the next week's session opens with a
cooked check-in, and dishes you cooked don't repeat within 4 weeks.

Conversation and curation are driven by the Claude API (Claude Sonnet 5); all
hard rules are enforced by deterministic Python code — *the model proposes,
the code disposes*.

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- An **Anthropic API key** — only needed to run the live bot or the marked
  live tests; the default test suite is fully offline
- A **Telegram bot token** — create a bot with
  [@BotFather](https://t.me/BotFather) (`/newbot`), then message your new bot
  once and get your numeric chat ID (e.g. via `@userinfobot`)

## Environment

```bash
# .env (or exported) — see src/sous_chef/config.py for the full list
ANTHROPIC_API_KEY=sk-ant-...
SOUS_CHEF_TELEGRAM_TOKEN=123456:ABC-...
SOUS_CHEF_CHAT_ID=123456789          # the single authorized chat
SOUS_CHEF_DB_PATH=./sous_chef.db     # SQLite file (created on first accept)
SOUS_CHEF_TZ=America/New_York        # ISO-week boundary timezone
SOUS_CHEF_MODEL=claude-sonnet-5      # config-swappable model id
```

## Setup

```bash
uv sync                       # install runtime + dev dependencies
uv run ruff check .           # lint — zero warnings
uv run ruff format --check .  # formatting
uv run mypy src/              # type checking
```

## Test

```bash
uv run pytest            # unit + contract + integration (fake LLM, temp SQLite)
uv run pytest -m live    # optional live-API smoke tests (needs ANTHROPIC_API_KEY)
```

The default suite is deterministic and needs no network: the only
nondeterministic component (the LLM) is replaced by a scripted fake transport,
and every test uses a temp database.

## Run

```bash
uv run python -m sous_chef
```

The process connects by long polling — no inbound ports, no webhook. Stop with
Ctrl-C; in-flight (unaccepted) session state is discarded by design, so an
abandoned session never touches the database.

### Commands

| Command | Behavior |
|---|---|
| `/start` | Welcome and how to begin |
| `/plan` | Begin (or resume) this week's planning conversation |
| `/history` | Summarize past weeks from history |
| `/cancel` | Abandon the current session — nothing is saved |
| any text | Conversational turn to the planning agent |

## Project layout

```
src/sous_chef/
├── config.py    # env-based settings
├── models/      # WeeklyPlan, grocery, history (Pydantic)
├── services/    # deterministic logic: validators, grocery merge, SQLite, weeks
├── agent/       # Claude conversation loop, client tools, system prompt
└── bot/         # Telegram transport, MarkdownV2 formatting, typing/ack
```

Design docs, contracts, and the full specification live in
[`specs/001-weekly-dinner-planner/`](specs/001-weekly-dinner-planner/) —
start with [`quickstart.md`](specs/001-weekly-dinner-planner/quickstart.md)
for the manual end-to-end validation walkthrough.
