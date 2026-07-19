# Quickstart: Weekly Dinner Planner

**Feature**: `001-weekly-dinner-planner` | **Date**: 2026-07-18

Runnable validation guide: how to set up, test, and manually verify the feature
end-to-end. Contracts: [contracts/](./contracts/) · Data model:
[data-model.md](./data-model.md) · Decisions: [research.md](./research.md).

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (or plain `pip`) for dependency management
- An **Anthropic API key** (`ANTHROPIC_API_KEY`) — only needed to run the live bot or
  the marked live tests; the default test suite is fully offline
- A **Telegram bot token** — create a bot with [@BotFather](https://t.me/BotFather)
  (`/newbot`), copy the token; then message the new bot once and get your numeric chat
  ID (e.g. via `@userinfobot`) for the allowlist

## Environment

```bash
# .env (or exported) — see src/sous_chef/config.py for the full list
ANTHROPIC_API_KEY=sk-ant-...
SOUS_CHEF_TELEGRAM_TOKEN=123456:ABC-...
SOUS_CHEF_CHAT_ID=123456789          # the single authorized chat
SOUS_CHEF_DB_PATH=./sous_chef.db     # SQLite file (created on first accept)
SOUS_CHEF_TZ=America/New_York        # ISO-week boundary timezone
SOUS_CHEF_MODEL=claude-sonnet-5      # config-swappable (research R4); token-efficient default
```

## Setup

```bash
uv sync                 # install runtime + dev dependencies
uv run ruff check .     # lint — must be zero warnings (constitution I)
uv run ruff format --check .
uv run mypy src/
```

## Run the test suite (offline, deterministic)

```bash
uv run pytest                    # unit + contract + integration (fake LLM, temp SQLite)
uv run pytest -m live            # optional: live-API smoke tests (needs both keys)
```

Expected outcome: all default tests pass with no network access; the suite is
order-independent and uses a temp database per test.

### Acceptance-scenario → test mapping (constitution II)

| Spec scenario | Test |
|---|---|
| US1 #1–6 (conversational planning, flags, swap, missing counts, mid-session prefs, priority explanation) | `tests/integration/test_story1_planning.py` |
| US2 #1–4 (flat grocery list, scaling, bill, regeneration on swap) | `tests/integration/test_story2_grocery.py` |
| US3 #1–5 (budget offer, decline, fit, overage, mid-session change) | `tests/integration/test_story3_budget.py` |
| US4 #1–6 (logging, 4-week no-repeat, check-in, recall, requested repeat, first session) | `tests/integration/test_story4_history.py` |
| Edge cases (counts out of range, zero lunches, vegan protein, relaxed window, abandoned session, skipped check-in, unsatisfiable constraints, search fallback) | `tests/integration/test_edge_cases.py` |
| Tool/schema drift | `tests/contract/test_tool_schemas.py`, `test_plan_schema.py` |
| Merge/bill/validator/window/week math | `tests/unit/` |
| SC-007 ordering (ack before agent call) | asserted inside `test_story1_planning.py` |

## Run the bot

```bash
uv run python -m sous_chef
```

The process starts long polling — no inbound ports, no webhook. Stop with Ctrl-C;
in-flight (unaccepted) session state is discarded by design.

## Manual end-to-end validation

Walk each story in Telegram against the running bot:

1. **First plan (US1, SC-008)** — send `/start`, then "I want to cook 3 dinners and
   2 lunches this week". Verify: typing indicator/ack appears immediately (SC-007);
   the proposed plan has exactly 3 dinners, one flagged batch meal stating it covers
   2 lunches + 1 dinner, one distinct flagged stretch meal with a named technique,
   and prep time + servings on every meal (SC-002) — with no other input demanded.
2. **Swap (US1 #3)** — reject one meal ("swap the salmon for something else").
   Verify only that meal changes and flags/counts still hold.
3. **Grocery list & bill (US2)** — accept the plan. Verify a single flat grocery list
   arrives with each ingredient exactly once (SC-003) and an estimated bill; swap a
   meal afterward and verify the list and bill regenerate.
4. **Budget (US3)** — start a new conversation turn, set "budget is $60 this week".
   Verify the plan's bill fits, or the overage is stated with an amount and
   cost-reducing options (SC-005). Remove the budget and verify the comparison
   disappears without a restart.
5. **History & check-in (US4)** — the following week, send `/plan`. Verify the bot
   first asks which of last week's meals were cooked; answer partially and verify a
   skipped meal may be re-proposed while cooked dishes are not (SC-004); ask "what
   did I cook last week?" and verify the answer matches; ask to repeat a past meal
   and verify it appears and counts toward the dinner count.
6. **Abandon (edge case)** — start a session, get a proposal, send `/cancel`.
   Restart the bot; verify no plan or history rows exist for that week
   (`sqlite3 sous_chef.db 'select * from plans;'`).

## Performance validation (SC-007)

- Visible response < 5 s: the typing indicator is emitted pre-agent-call by contract
  (see [contracts/telegram-bot.md](./contracts/telegram-bot.md)); observe it appears
  immediately on any message.
- Draft plan < 30 s: measured by the marked live test
  (`pytest -m live -k draft_latency`) and observable manually from send → plan
  message.
