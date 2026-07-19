# Tasks: Weekly Dinner Planner

**Input**: Design documents from `/specs/001-weekly-dinner-planner/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are MANDATORY per Constitution Principle II (Testing Standards). Every user story phase includes test tasks ordered before implementation tasks; each acceptance scenario maps to at least one test (mapping in quickstart.md). Write tests first and observe them FAIL before implementing.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Single project per plan.md: `src/sous_chef/` and `tests/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, tooling, and CI per research R2/R14

- [X] T001 Create project skeleton: `pyproject.toml` (uv-managed; runtime deps `anthropic`, `python-telegram-bot` v22, `pydantic` v2; dev deps `pytest`, `pytest-asyncio`, `ruff`, `mypy`), package dirs `src/sous_chef/{models,services,agent,bot}/` with `__init__.py` files, test dirs `tests/{contract,integration,unit}/`, and pytest config registering the `live` marker excluded from the default run (`-m "not live"`)
- [X] T002 [P] Configure `ruff` (lint + format, zero-warning gate) and `mypy` (`disallow_untyped_defs` on `src/`) in `pyproject.toml`
- [X] T003 [P] Add GitHub Actions workflow running `ruff check`, `ruff format --check`, `mypy src/`, and `pytest` on every PR in `.github/workflows/ci.yml`
- [X] T004 Implement env-based settings (ANTHROPIC_API_KEY, SOUS_CHEF_TELEGRAM_TOKEN, SOUS_CHEF_CHAT_ID, SOUS_CHEF_DB_PATH, SOUS_CHEF_TZ, SOUS_CHEF_MODEL defaulting to `claude-sonnet-5`) in `src/sous_chef/config.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Typed domain models, week identity, storage bootstrap, agent/bot skeletons, and the fake LLM transport that every story's integration tests drive

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Tests (write first, observe FAIL)

- [ ] T005 [P] Unit tests for ISO-week identity and lifecycle (week_id computation in configured timezone, Monday-start boundaries, previous-4-weeks window, week-end transition to `final`) in `tests/unit/test_weeks.py`
- [ ] T006 [P] Contract test: WeeklyPlan Pydantic model JSON schema round-trips against `specs/001-weekly-dinner-planner/contracts/weekly-plan.schema.json` (strict, `additionalProperties: false` throughout) in `tests/contract/test_plan_schema.py`

### Implementation

- [ ] T007 [P] Create WeeklyPlan, Meal, BatchDetails, StretchDetails, Ingredient Pydantic models (fields and constraints per data-model.md, incl. `normalized_name` derivation and `status` enum draft/accepted/final) in `src/sous_chef/models/plan.py`
- [ ] T008 [P] Create GroceryList and GroceryItem models (items, `estimated_total_usd`, `budget_delta_usd`, compound quantities) in `src/sous_chef/models/grocery.py`
- [ ] T009 [P] Create MealHistoryEntry, CookedStatus enum (planned/cooked/skipped), CheckinResult models in `src/sous_chef/models/history.py`
- [ ] T010 [P] Implement week service (current `week_id` like `2026-W30` in SOUS_CHEF_TZ, 4-week lookback list, lazy week-end finalization predicate) in `src/sous_chef/services/weeks.py`
- [ ] T011 Implement SQLite bootstrap in `src/sous_chef/services/history_repo.py`: connection management and schema creation for `plans` and `meals` tables plus `idx_meals_cooked` index exactly per data-model.md
- [ ] T012 Implement Anthropic client setup in `src/sous_chef/agent/client.py`: model/config from `config.py`, adaptive thinking, streaming, prompt caching on stable prefix, beta tool runner invocation with `pause_turn` restart handling capped at 5 restarts (research R6)
- [ ] T013 Implement in-memory SessionState (chat_id, messages, dinner/lunch counts, diet_type, default_servings, weekly_budget_usd, staged_draft, repetition_relaxed, pending_checkin) and the per-chat message loop in `src/sous_chef/agent/session.py`; abandoning a session discards the object with no persistence (FR-021)
- [ ] T014 Implement scripted fake LLM transport exposing the same interface as `agent/client.py` and replaying scripted tool-call/text transcripts deterministically offline in `tests/integration/fake_llm.py`
- [ ] T015 Implement Telegram Application in `src/sous_chef/bot/app.py`: long polling, single-chat-ID allowlist ("this is a private bot" refusal, no state change), command handlers `/start`, `/plan`, `/history`, `/cancel`, and plain-text forwarding to the agent session per contracts/telegram-bot.md
- [ ] T016 [P] Implement typing indicator sent before any agent call, refreshed every ~4 s until reply, plus immediate ack message for plan-generation turns in `src/sous_chef/bot/ack.py` (SC-007, FR-027)
- [ ] T017 Implement entry point wiring config → history_repo → agent client/session → bot application in `src/sous_chef/__main__.py` (`python -m sous_chef`)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Plan a Week of Dinners and Lunches Conversationally (Priority: P1) 🎯 MVP

**Goal**: Conversational curation of a weekly plan: user supplies only dinner + lunch counts; agent proposes healthy high-protein dinners with exactly one batch meal (covering all lunches + one dinner) and one distinct stretch meal, prep time and servings on every meal, with reject/swap before acceptance.

**Independent Test**: Run a first-ever session (no history, no budget) providing only a dinner count and lunch count; verify the proposed plan has the requested dinners, correctly flagged batch and stretch meals, and prep time + serving size on every meal — with no other input demanded (spec US1 Independent Test).

### Tests for User Story 1 (MANDATORY — write first, observe FAIL) ⚠️

- [ ] T018 [P] [US1] Contract test pinning the generated `propose_plan` tool schema (`strict: true`, WeeklyPlan payload input, result shape incl. error codes table) against `specs/001-weekly-dinner-planner/contracts/agent-tools.md` and `weekly-plan.schema.json` in `tests/contract/test_tool_schemas.py`
- [ ] T019 [P] [US1] Unit tests for plan validators — nominal/boundary/error cases for dinner_count 3–4, lunch_count 0–7, meal-count match, exactly one batch + one distinct stretch (incl. 3-meal two-flags edge case), batch `total_portions == (lunch_count + 1) × servings`, zero-lunch batch coverage, required `primary_protein`/`prep_minutes`/`servings`/non-empty ingredients — in `tests/unit/test_plan_validator.py`
- [ ] T020 [P] [US1] Integration tests driving the real session loop with the fake LLM for US1 acceptance scenarios 1–6 (propose with counts only; batch+stretch flags stated; single-meal swap preserves the rest; missing counts prompted before proposing; mid-session diet/serving preference applied without restart; priority-order explanation), asserting ack/typing emitted BEFORE the agent call (SC-007 ordering), in `tests/integration/test_story1_planning.py`

### Implementation for User Story 1

- [ ] T021 [P] [US1] Implement deterministic plan validators (rules from T019; error codes `dinner_count_out_of_range`, `lunch_count_out_of_range`, `meal_count_mismatch`, `batch_meal_count`, `stretch_meal_count`, `batch_stretch_same_meal`, `batch_coverage_mismatch`, `missing_field`, `invalid_value` per contracts/agent-tools.md) in `src/sous_chef/services/plan_validator.py`
- [ ] T022 [US1] Implement `propose_plan` client tool (`@beta_tool`, `strict: true`): parse WeeklyPlan payload into Pydantic models, run validators, on failure return `ok: false` with error list for self-correction, on success stage draft in SessionState and return grocery/bill preview stub in `src/sous_chef/agent/tools.py` (depends on T021)
- [ ] T023 [P] [US1] Write the system prompt in `src/sous_chef/agent/prompt.py`: cache-stable prefix; require dinner+lunch counts before curating; nutrition > budget > prep time > skill-building priority order and explanations on request; healthy/high-protein athlete framing with primary protein named; batch/stretch flag semantics; canonical terminology from data-model.md; web-search fallback to own knowledge (edge case); constraint-conflict messaging per FR-028
- [ ] T024 [US1] Declare the server web-search tool (`{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}`) in the agent tool list and map result citations to meal `source_url` in `src/sous_chef/agent/client.py` and `src/sous_chef/agent/tools.py` (FR-010)
- [ ] T025 [P] [US1] Implement MarkdownV2 plan rendering in `src/sous_chef/bot/formatting.py`: one meal per block — bold name, flag lines (`🍲 Batch meal — covers N lunches + 1 dinner (P portions)`, `✨ Stretch meal — new technique: X`), `⏱` prep, `🍽` servings, `🥩` protein, `🔗` source when present; open nights listed at end; reserved characters escaped
- [ ] T026 [US1] Wire the session flow in `src/sous_chef/agent/session.py`: block curation until both counts known (prompting for whichever is missing), route reject/swap turns through a fresh `propose_plan`, apply mid-session preferences without restarting, deliver rendered plan through the bot (depends on T022, T023, T025)

**Checkpoint**: User Story 1 fully functional — a plan can be conversationally curated and presented (not yet persisted). MVP demoable via Telegram.

---

## Phase 4: User Story 2 - Get a Grocery List and Estimated Bill (Priority: P2)

**Goal**: Accepting a plan produces one flat merged grocery list (each ingredient exactly once, quantities scaled and combined) with a deterministic estimated weekly bill; both regenerate on any post-acceptance change.

**Independent Test**: Accept any plan and verify the grocery list contains every ingredient required by the plan's meals exactly once with combined quantities, accompanied by a single estimated total bill; swap a meal and verify both regenerate (spec US2 Independent Test).

### Tests for User Story 2 (MANDATORY — write first, observe FAIL) ⚠️

- [ ] T027 [P] [US2] Contract test pinning the generated `accept_plan` tool schema and result shape (grocery_list items/total/budget_delta, `meals_logged`; errors `no_staged_draft`, `week_mismatch`, `week_already_final`) against `specs/001-weekly-dinner-planner/contracts/agent-tools.md` in `tests/contract/test_tool_schemas.py`
- [ ] T028 [P] [US2] Unit tests for grocery merging — name normalization (casefold, trim, simple-plural singularize), unit-family conversion (mass g/kg/oz/lb; volume ml/l/tsp/tbsp/cup; count), unmergeable units rendered as compound quantity ("2 cups + 1 can"), each normalized ingredient exactly once (SC-003), batch-meal full-coverage scaling — in `tests/unit/test_grocery_merge.py`
- [ ] T029 [P] [US2] Unit tests for bill totaling — sum of item price estimates, empty/zero-price boundaries, totals computed not generated — in `tests/unit/test_bill_math.py`
- [ ] T030 [P] [US2] Integration tests for US2 acceptance scenarios 1–4 (flat merged list on accept; quantities reflect serving sizes incl. batch lunch coverage; bill accompanies list; swap after acceptance regenerates list and bill) in `tests/integration/test_story2_grocery.py`

### Implementation for User Story 2

- [ ] T031 [P] [US2] Implement deterministic grocery merge and bill totaling (rules from T028/T029; returns GroceryList with `estimated_total_usd` and optional `budget_delta_usd`) in `src/sous_chef/services/grocery.py`
- [ ] T032 [US2] Implement plan persistence in `src/sous_chef/services/history_repo.py`: upsert accepted plan on `week_id` (plans row with plan_json/grocery_json/timestamps + meals rows with flags and technique), superseded intra-week versions overwritten (FR-022)
- [ ] T033 [US2] Implement `accept_plan` client tool: verify staged draft matches `week_id`, compute grocery list via `services/grocery.py`, persist via `history_repo`, return final artifacts, in `src/sous_chef/agent/tools.py` (depends on T031, T032); wire real grocery/bill preview into `propose_plan`'s result (replacing T022 stub)
- [ ] T034 [US2] Implement grocery-list MarkdownV2 message in `src/sous_chef/bot/formatting.py`: separate message, one item per line `• name — quantity (est. $x.xx)`, final `Estimated bill: $XX.XX` line, items/totals verbatim from `accept_plan` result, 4096-char splits at line boundaries never mid-item
- [ ] T035 [US2] Wire post-acceptance edits in `src/sous_chef/agent/session.py`: meal swap or serving change re-enters `propose_plan` → `accept_plan`, upserts the same week and re-presents regenerated artifacts (FR-015, FR-022)

**Checkpoint**: User Stories 1 AND 2 work — accepted plans persist and yield deterministic grocery list + bill

---

## Phase 5: User Story 3 - Plan Within a Weekly Grocery Budget (Priority: P3)

**Goal**: Optional weekly budget offered at conversation start; plans fit it when set; when nutrition forces an overage, the exact amount is stated with cost-reducing adjustments; budget is settable/changeable/removable mid-session and never carried across weeks.

**Independent Test**: Set a weekly budget at session start, request a plan, and verify the estimated bill is at or below budget — or the overage is explicitly stated with an amount and adjustment options (spec US3 Independent Test).

### Tests for User Story 3 (MANDATORY — write first, observe FAIL) ⚠️

- [ ] T036 [P] [US3] Unit tests for budget comparison — `budget_delta_usd` null without budget, negative under budget, positive overage with exact amount; over-budget plan staged not rejected — extending `tests/unit/test_bill_math.py`
- [ ] T037 [P] [US3] Integration tests for US3 acceptance scenarios 1–5 (budget offered at start and declining doesn't block; no comparison when declined; bill fits when set; overage stated with amount + nutrition-preserving adjustments; mid-session change/removal updates comparison without restart) in `tests/integration/test_story3_budget.py`

### Implementation for User Story 3

- [ ] T038 [US3] Implement budget-delta computation in `src/sous_chef/services/grocery.py` and surface it through `propose_plan`/`accept_plan` results in `src/sous_chef/services/plan_validator.py` and `src/sous_chef/agent/tools.py` — over-budget plans return the overage, never a rejection (FR-018/FR-020, nutrition wins per FR-008)
- [ ] T039 [US3] Extend the system prompt in `src/sous_chef/agent/prompt.py`: offer the budget option at the start of every planning conversation (declining never blocks), accept set/change/remove at any point before acceptance, state overage amounts plainly and offer cost-reducing adjustments that keep the nutrition standard, never carry a budget across weeks (FR-016/FR-017)
- [ ] T040 [US3] Render the budget comparison line `(budget $YY — under/over by $Z)` on the grocery-list message when a budget is set in `src/sous_chef/bot/formatting.py`

**Checkpoint**: Budget-aware planning works end-to-end; Stories 1–3 independently functional

---

## Phase 6: User Story 4 - Remember Past Weeks and Avoid Repetition (Priority: P4)

**Goal**: Accepted plans log to history; next session opens with a cooked check-in; cooked dishes don't repeat within 4 weeks (with announced relaxation when needed); past weeks are queryable and past meals recallable into the current plan; stretch techniques are new relative to cooked history.

**Independent Test**: Accept plans in two consecutive weeks and verify week two proposes no main dish cooked in week one, then ask the agent to list week one's meals and to re-add one of them (spec US4 Independent Test).

### Tests for User Story 4 (MANDATORY — write first, observe FAIL) ⚠️

- [ ] T041 [P] [US4] Contract tests pinning the generated `get_meal_history` and `record_cooked_checkin` tool schemas and result shapes (incl. `pending_checkin_week_id`, `cooked_dish_names_last_4_weeks`, `known_techniques`; check-in errors `unknown_week`/`unknown_meal_name`/`already_recorded`) against `specs/001-weekly-dinner-planner/contracts/agent-tools.md` in `tests/contract/test_tool_schemas.py`
- [ ] T042 [P] [US4] Unit tests for the repetition window — normalized-name matching (chicken chili twice = repeat, beef chili ≠ chicken chili), cooked-only rows count, skipped meals re-proposable, `user_requested_repeat` bypass, announced-relaxation bypass, 4-ISO-week boundary, stretch-technique novelty vs cooked history only — in `tests/unit/test_repetition_window.py`
- [ ] T043 [P] [US4] Integration tests for US4 acceptance scenarios 1–6 (meals logged with week on acceptance; no cooked dish from previous 4 weeks repeats; check-in asked before curating and skipped meals may reappear; past-week query answered from history; explicit repeat included and counted; first-ever session runs with no check-in and no repetition rule) in `tests/integration/test_story4_history.py`

### Implementation for User Story 4

- [ ] T044 [US4] Implement history queries in `src/sous_chef/services/history_repo.py`: cooked normalized names in the 4 ISO weeks before a target week, distinct cooked stretch techniques, meals by week_id and lookup by normalized name for recall, pending check-in detection (most recent `final` week with `planned` rows), lazy finalization of past weeks on session start (research R11)
- [ ] T045 [US4] Implement `get_meal_history` client tool (weeks_back default 8; returns current_week_id, pending_checkin_week_id, cooked_dish_names_last_4_weeks, known_techniques, per-week meals) in `src/sous_chef/agent/tools.py` (depends on T044)
- [ ] T046 [US4] Implement `record_cooked_checkin` client tool: mark listed meals cooked and unlisted meals skipped; `user_skipped_checkin: true` marks every planned meal cooked; error results for unknown week/meal/already recorded, in `src/sous_chef/agent/tools.py` (depends on T044)
- [ ] T047 [US4] Extend validators in `src/sous_chef/services/plan_validator.py` with cooked-history rules: `repeated_dish` (normalized name cooked within 4 weeks, honoring `user_requested_repeat` and session relaxation flag, message listing offending names) and `technique_not_new` (stretch technique already in cooked history) (depends on T044)
- [ ] T048 [US4] Wire history behavior in `src/sous_chef/agent/session.py` and `src/sous_chef/agent/prompt.py`: call `get_meal_history` before the first proposal of a session, run the cooked check-in before curating when `pending_checkin_week_id` is non-null, announced repetition-window relaxation (oldest first) setting `repetition_relaxed`, past-week questions and recall-by-reference into the current plan (FR-021/023/024)

**Checkpoint**: All user stories independently functional; history compounds week over week

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Edge-case coverage, error states, performance validation, docs, and final verification

- [ ] T049 Integration tests for the spec Edge Cases section (dinner count outside 3–4 re-prompted; zero lunches noted; >7 lunches rejected; vegan protein adaptation explained; relaxed-window announcement; serving change after acceptance recalculates; abandoned session leaves no rows; skipped check-in defaults to cooked; unsatisfiable constraints name the failed constraint; web-search failure falls back to own knowledge) in `tests/integration/test_edge_cases.py`
- [ ] T050 Implement transport error states per contracts/telegram-bot.md in `src/sous_chef/bot/app.py`: agent/API failure replies "I hit a problem generating that — nothing was saved…" with session state retained for retry; Telegram delivery failures retried without duplicate side effects (accept_plan idempotent per week upsert); `/history` empty-state message for first-ever use
- [ ] T051 [P] Add live-API smoke tests marked `live` (excluded by default): end-to-end plan generation and draft-plan latency < 30 s (`-k draft_latency`, SC-007) in `tests/integration/test_live_smoke.py`
- [ ] T052 [P] Add performance budget assertions for non-LLM paths (grocery merge, plan validation, history queries each < 200 ms per constitution Principle IV) in `tests/unit/test_performance_budgets.py`
- [ ] T053 [P] Write README.md with setup, environment, test, and run instructions distilled from `specs/001-weekly-dinner-planner/quickstart.md`
- [ ] T054 Code cleanup pass: `ruff check` and `ruff format --check` zero warnings, `mypy src/` clean, no dead code or speculative abstractions (constitution Principle I)
- [ ] T055 Run the quickstart.md manual end-to-end validation (all 6 walkthrough steps against the live bot) and record results in `specs/001-weekly-dinner-planner/quickstart.md` checklist notes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Stories (Phases 3–6)**: All depend on Foundational completion
  - Recommended: sequential in priority order (P1 → P2 → P3 → P4) — this is a solo project and later stories extend files created in earlier ones (`tools.py`, `formatting.py`, `prompt.py`, `plan_validator.py`)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Only Foundational. Delivers the MVP (plan curation, no persistence).
- **US2 (P2)**: Foundational + US1's `propose_plan`/staging (T022) — acceptance operates on a staged draft.
- **US3 (P3)**: Foundational + US2's grocery/bill computation (T031) — budget comparison needs a computed bill.
- **US4 (P4)**: Foundational + US1's validators (T021); integrates with acceptance logging from US2 (T032) for its integration tests.

### Within Each User Story

- Tests MUST be written and observed to FAIL before implementation (constitution Principle II)
- Models → services → tools → session/bot wiring
- Story checkpoint reached before starting the next story

### Key Task-Level Dependencies

- T022 depends on T021 · T026 depends on T022, T023, T025
- T033 depends on T031, T032 · T035 depends on T033
- T038 depends on T031 · T045/T046/T047 depend on T044 · T048 depends on T045–T047

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests together (different files):
Task: "T018 Contract test pinning propose_plan schema in tests/contract/test_tool_schemas.py"
Task: "T019 Unit tests for plan validators in tests/unit/test_plan_validator.py"
Task: "T020 Integration tests for US1 scenarios 1–6 in tests/integration/test_story1_planning.py"

# Then start independent implementation files together:
Task: "T021 Plan validators in src/sous_chef/services/plan_validator.py"
Task: "T023 System prompt in src/sous_chef/agent/prompt.py"
Task: "T025 MarkdownV2 plan rendering in src/sous_chef/bot/formatting.py"
```

Similar fan-out applies in Phase 2 (T005–T006 together, then T007–T010 together) and in each story's test block (US2: T027–T030; US3: T036–T037; US4: T041–T043).

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T004)
2. Complete Phase 2: Foundational (T005–T017) — CRITICAL, blocks all stories
3. Complete Phase 3: User Story 1 (T018–T026)
4. **STOP and VALIDATE**: run `uv run pytest`; walk quickstart step 1–2 in Telegram
5. Demo: a full conversational planning session with flagged batch/stretch meals

### Incremental Delivery

1. Setup + Foundational → skeleton bot answers on Telegram
2. Add US1 → conversational plan curation (MVP!)
3. Add US2 → acceptance persists the plan and delivers grocery list + bill
4. Add US3 → budget-aware curation and overage reporting
5. Add US4 → check-ins, repetition avoidance, recall
6. Polish → edge cases, error states, performance assertions, live smoke tests, docs

Each story adds value without breaking previous stories; every checkpoint is a demoable state.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- Later stories intentionally extend shared files (`agent/tools.py`, `bot/formatting.py`, `agent/prompt.py`, `services/plan_validator.py`) — do not parallelize across stories
- Verify tests fail before implementing (Red-Green-Refactor)
- Commit after each task or logical group (constitution: small, scoped commits)
- The default test suite must stay offline and deterministic; only `-m live` touches the network
