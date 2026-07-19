# Data Model: Weekly Dinner Planner

**Feature**: `001-weekly-dinner-planner` | **Date**: 2026-07-18

Canonical domain terminology (used verbatim in code, tests, and every user-facing
message — constitution Principle III): **plan**, **meal**, **batch meal**,
**stretch meal**, **grocery list**, **estimated bill**, **budget**, **prep time**,
**serving**, **technique**, **cooked / skipped**.

## Entity Overview

```
SessionState (in-memory, per chat) ──stages──▶ WeeklyPlan ──contains──▶ Meal ──has──▶ Ingredient
                                                   │                      │
                                                   │ derives              │ one may carry BatchDetails
                                                   ▼                      │ one may carry StretchDetails
                                              GroceryList ──▶ GroceryItem
                                                   │
WeeklyPlan (accepted) ──persisted as──▶ plans row + meals rows (SQLite)
meals rows ──updated by──▶ CookedCheckin (next session)
```

## Entities

### WeeklyPlan

One week's plan. Exactly one per ISO week (FR-022). Staged in memory as a draft;
persisted on acceptance.

| Field | Type | Constraints / Source |
|---|---|---|
| `week_id` | str | ISO week, e.g. `2026-W30`; primary identity (R11) |
| `dinner_count` | int | Required; validator enforces 3–4 (FR-004) |
| `lunch_count` | int | Required; validator enforces 0–7 (FR-002, edge cases) |
| `diet_type` | str \| None | Optional preference; None = no restriction (FR-003) |
| `default_servings` | int | Defaults to 1 (spec assumption) |
| `weekly_budget_usd` | float \| None | Optional; applies to this week only (FR-016/017) |
| `meals` | list[Meal] | len == `dinner_count` (lunches are covered by the batch meal, not separate dishes) |
| `status` | enum `draft` \| `accepted` \| `final` | See state transitions |
| `accepted_at` | datetime \| None | Set on acceptance |

**Validation rules** (deterministic, `plan_validator.py`):
- `len(meals) == dinner_count`, and `3 <= dinner_count <= 4` (FR-004).
- `0 <= lunch_count <= 7` (edge cases).
- Exactly one meal has `batch` details; exactly one *different* meal has `stretch`
  details (FR-005/006; edge case: with 3 meals, two of the three carry the flags).
- Batch meal `total_portions == lunch_count + 1` × its per-person serving count
  (FR-005, FR-014); with `lunch_count == 0` the batch meal covers only its dinner
  night (edge case).
- Stretch technique (normalized) must not appear in cooked-meal technique history
  (FR-006); a technique from a planned-but-uncooked stretch meal is still "new".
- No meal's normalized name may match a cooked main dish from the previous 4 weeks,
  unless the meal is marked `user_requested_repeat` or the session is in announced
  relaxation mode (FR-023, R10).
- Every meal has `primary_protein`, `prep_minutes > 0`, `servings > 0` (FR-007/013/014).
- If `weekly_budget_usd` is set: computed estimated bill compared against it; an
  over-budget plan is *not* rejected — the validator returns the overage amount so
  the agent can surface it with adjustments (FR-020; nutrition wins per FR-008).

### Meal

A single dish in a plan.

| Field | Type | Constraints / Source |
|---|---|---|
| `name` | str | Display name; `normalized_name` derived (casefold/trim) for repetition matching |
| `primary_protein` | str | Required (FR-007) |
| `prep_minutes` | int | Required, > 0 (FR-013) |
| `servings` | int | Per-cooking-night servings (FR-014); defaults to plan `default_servings` |
| `batch` | BatchDetails \| None | Non-null on exactly one meal per plan |
| `stretch` | StretchDetails \| None | Non-null on exactly one (different) meal per plan |
| `source_url` | str \| None | Set when based on a web recipe (FR-010) |
| `user_requested_repeat` | bool | True only when the user explicitly asked for this past meal (FR-023/024) |
| `ingredients` | list[Ingredient] | Non-empty; quantities scaled to this meal's full coverage |

**BatchDetails**: `lunches_covered: int` (== plan `lunch_count`),
`total_portions: int` (lunches + 1 dinner night, × servings) (FR-005/014).

**StretchDetails**: `technique: str` — the named new technique (FR-006).

### Ingredient (per meal)

| Field | Type | Constraints |
|---|---|---|
| `name` | str | Non-empty; normalized for merging (R9) |
| `quantity` | float | > 0 |
| `unit` | str | Unit token (`g`, `kg`, `oz`, `lb`, `ml`, `l`, `tsp`, `tbsp`, `cup`, `count`, free-form like `can`) |
| `estimated_price_usd` | float | ≥ 0; good-faith estimate supplied by the agent (spec assumption) |

### GroceryList (derived — never stored independently of its plan)

Computed deterministically from an accepted plan's meals (R9); regenerated whenever
the plan changes (FR-015).

| Field | Type | Constraints |
|---|---|---|
| `items` | list[GroceryItem] | Each normalized ingredient name appears exactly once (SC-003) |
| `estimated_total_usd` | float | Sum of item prices (FR-012); computed, not generated |
| `budget_delta_usd` | float \| None | `estimated_total_usd - weekly_budget_usd` when a budget is set; positive = overage (FR-020) |

**GroceryItem**: `name` (normalized display name), `quantities` (list of
`(amount, unit)` pairs — one entry when units merge, multiple when unmergeable),
`estimated_price_usd` (summed).

### MealHistoryEntry (persisted per meal per week)

The sole source of "what the user has cooked" (FR-025).

| Field | Type | Constraints |
|---|---|---|
| `week_id` | str | FK to plan |
| `meal_name` / `normalized_name` | str | For recall and repetition matching |
| `is_batch` / `is_stretch` | bool | Flags as planned |
| `technique` | str \| None | Set for stretch meals |
| `cooked_status` | enum `planned` \| `cooked` \| `skipped` | See transitions |

### CookedCheckin (transient)

Produced at the start of a session when the most recent `final`-week plan has meals
still in `planned` status (FR-021). Result: per-meal `cooked`/`skipped` marks, or
`skipped_checkin = True` → all meals default to `cooked`.

### SessionState (in-memory only — never persisted)

| Field | Type | Notes |
|---|---|---|
| `chat_id` | int | Allowlisted single user |
| `messages` | list | Claude conversation history for this session |
| `dinner_count` / `lunch_count` | int \| None | Required before curation (FR-002) |
| `diet_type`, `default_servings`, `weekly_budget_usd` | optional | Applied mid-session without restart (FR-003, FR-016) |
| `staged_draft` | WeeklyPlan \| None | Last payload accepted by `propose_plan` |
| `repetition_relaxed` | bool | Set when the agent announces window relaxation (R10) |
| `pending_checkin` | CookedCheckin \| None | Cleared once recorded or skipped |

Abandoning the session (process restart, user silence) discards this object — nothing
reaches SQLite until `accept_plan` (FR-021, edge case).

## State Transitions

**WeeklyPlan.status**

```
draft ──accept_plan──▶ accepted ──(week ends; evaluated lazily at next session)──▶ final
  ▲                        │
  └──propose_plan (edit)───┘        accepted plans re-enter draft staging on edit and
                                    are re-accepted (upsert on week_id) — FR-015/022
```

- Only `accepted` reaches storage; `draft` lives in SessionState.
- `final` is immutable; superseded intra-week versions are overwritten, so history
  records only the week's final state (FR-022).

**MealHistoryEntry.cooked_status**

```
planned ──checkin: "cooked" / checkin skipped or unanswered──▶ cooked
planned ──checkin: "skipped"──▶ skipped
```

- Set exactly once, by the next session's check-in (FR-021).
- Only `cooked` rows count for repetition avoidance and technique history; `skipped`
  meals may be re-proposed (FR-023) and their stretch techniques remain "new" (FR-006).

## SQLite Schema

```sql
CREATE TABLE plans (
    week_id      TEXT PRIMARY KEY,          -- '2026-W30'
    status       TEXT NOT NULL CHECK (status IN ('accepted', 'final')),
    plan_json    TEXT NOT NULL,             -- full WeeklyPlan payload
    grocery_json TEXT NOT NULL,             -- derived GroceryList (kept for recall/regen diffing)
    accepted_at  TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE meals (
    week_id         TEXT NOT NULL REFERENCES plans(week_id) ON DELETE CASCADE,
    meal_name       TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    is_batch        INTEGER NOT NULL DEFAULT 0,
    is_stretch      INTEGER NOT NULL DEFAULT 0,
    technique       TEXT,
    cooked_status   TEXT NOT NULL DEFAULT 'planned'
                    CHECK (cooked_status IN ('planned', 'cooked', 'skipped')),
    PRIMARY KEY (week_id, normalized_name)
);

CREATE INDEX idx_meals_cooked ON meals (cooked_status, week_id);
```

Key queries owned by `history_repo.py`:
- **Repetition window**: normalized names with `cooked_status = 'cooked'` in the 4 ISO
  weeks preceding the target week (FR-023).
- **Technique history**: distinct `technique` where `is_stretch = 1 AND
  cooked_status = 'cooked'` (FR-006).
- **Recall**: meals by `week_id` ("what did I cook two weeks ago?"), meal lookup by
  normalized name for "put that chili back" (FR-024).
- **Pending check-in**: most recent `final` week having any `planned` rows (FR-021).
