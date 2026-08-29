# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-user Telegram bot that plans a week of dinners/lunches conversationally via the Claude API. Core design rule: **the model proposes, the code disposes** — the LLM drives conversation and curation, but every hard rule (meal counts, batch/stretch constraints, 4-week repetition window, grocery math) is enforced by deterministic Python in `services/`.

## Commands

Everything runs through `uv`:

```bash
uv sync                       # install deps
uv run ruff check .           # lint (zero warnings required)
uv run ruff format --check .  # format check (ruff format . to fix)
uv run mypy src/              # type check (strict: disallow_untyped_defs)
uv run pytest                 # full offline suite (unit + contract + integration)
uv run pytest tests/unit/test_plan_validator.py             # one file
uv run pytest tests/unit/test_plan_validator.py -k name     # one test
uv run pytest -m live         # live-API smoke tests (needs ANTHROPIC_API_KEY; excluded by default via addopts)
```

CI (`.github/workflows/ci.yml`) runs exactly: ruff check, ruff format --check, mypy src/, pytest. All four must be green.

To run/stop/inspect the bot itself, use the `sous-chef-service` skill (which drives `./scripts/sous-chef-ctl run|stop|status|logs|errors`). Never launch `python -m sous_chef` directly alongside it — two pollers on one bot token cause Telegram 409 conflicts. Config is env-based via `.env`; the full variable list is in `src/sous_chef/config.py`.

## Architecture

Data flow for one conversational turn: Telegram update → `bot/app.py` (long polling, single-chat allowlist) → `Session.handle_message` (`agent/session.py`) → `Transport.run_turn` (`agent/client.py`) → Claude API with client tools (`agent/tools.py`) → tools call `services/` → `TurnOutcome` back to the bot for MarkdownV2 rendering (`bot/formatting.py`).

Key seams and invariants:

- **`Transport` protocol** (`agent/client.py`) is the test seam: it runs one full agentic turn (model ↔ tools until the model stops calling tools). Integration tests replace it with a scripted fake (`tests/integration/fake_llm.py`), so the default suite is fully offline and deterministic.
- **`Session` is in-memory only** (`agent/session.py`). Nothing touches SQLite until the agent's `accept_plan` tool runs; `/cancel` or a process restart discards state by design. `Session.handle_message` detects new staged drafts / acceptances by object identity before vs. after the turn.
- **Tools are built per session** (`agent/tools.py`, factory pattern): each tool closes over its `Session` to stage drafts into that session's state. Tool results are JSON with a top-level `ok` flag — validation failures return error-code lists for the model to self-correct from, never exceptions, and are never shown raw to the user.
- **`services/`** holds all deterministic logic: `plan_validator.py` (rule enforcement with stable error codes), `grocery.py` (list merge + bill math), `history_repo.py` (SQLite persistence, cooked check-ins, meal instructions), `weeks.py` (ISO-week IDs in the configured timezone).
- **`models/`** are Pydantic v2 models (`WeeklyPlan`, grocery, history); the mypy pydantic plugin is enabled.
- **No DB migrations exist.** Schema changes mean deleting `sous_chef.db` (it is recreated on the next accepted plan). Call this out in any change that alters the schema.

Test layout mirrors this: `tests/unit/` covers services/business logic, `tests/contract/` pins the plan schema and tool schemas, `tests/integration/` plays scripted conversations per user story through the fake transport with a temp database.

## Engineering rules

- **Test-first is non-negotiable**: tests are written and observed to fail before implementation; a contract or schema change without a test change must be rejected.
- Tests must be deterministic — independent of network, ordering, and wall-clock time (inject `now`/`tz` as `Session` does).
- Zero lint warnings; no dead code, commented-out blocks, or speculative abstractions; comments only for constraints the code cannot express.
