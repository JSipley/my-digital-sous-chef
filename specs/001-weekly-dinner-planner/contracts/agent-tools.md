# Contract: Agent Tools

**Feature**: `001-weekly-dinner-planner` | **Date**: 2026-07-18

The conversation loop exposes exactly seven tools to the model. Six are client tools
implemented in `agent/tools.py` (wired to `services/`); one is the Anthropic
server-side web-search tool. Contract tests (`tests/contract/test_tool_schemas.py`)
assert that the schemas generated from the implementation match this document and
`weekly-plan.schema.json` — any drift is a failing test.

Conventions:
- All client tool results are JSON objects with a top-level `"ok": boolean`. When
  `"ok": false`, `"errors"` is a non-empty list of `{code, message}` objects written
  for the model to act on (self-correct or explain to the user per FR-028).
- Tool errors never raise; failures return `is_error` tool results with a message.

---

## 1. `get_meal_history` (client)

Read-only access to accumulated history (FR-023, FR-024, FR-006). Also returns any
pending cooked check-in so the agent knows to run it before curating (FR-021).

**Input schema**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "weeks_back": {
      "type": "integer",
      "description": "How many past weeks to return, most recent first. Default 8."
    }
  },
  "required": []
}
```

**Result**

```json
{
  "ok": true,
  "current_week_id": "2026-W30",
  "pending_checkin_week_id": "2026-W29",
  "cooked_dish_names_last_4_weeks": ["chicken chili", "salmon teriyaki"],
  "known_techniques": ["searing", "braising"],
  "weeks": [
    {
      "week_id": "2026-W29",
      "status": "final",
      "meals": [
        {
          "name": "Chicken chili",
          "is_batch": true,
          "is_stretch": false,
          "technique": null,
          "cooked_status": "cooked"
        }
      ]
    }
  ]
}
```

`pending_checkin_week_id` is `null` when no check-in is due (first-ever session, or
already recorded). `weeks` is empty on a first-ever session — planning proceeds with
no repetition rule and no check-in (US4 scenario 6).

---

## 2. `record_cooked_checkin` (client)

Persists which of the pending week's planned meals were actually cooked (FR-021).

**Input schema**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "week_id": { "type": "string", "description": "The week being checked in, from pending_checkin_week_id." },
    "cooked_meal_names": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Names of the meals the user actually cooked. Meals of that week not listed are marked skipped."
    },
    "user_skipped_checkin": {
      "type": "boolean",
      "description": "True when the user skipped or could not recall the check-in; every planned meal is then marked cooked."
    }
  },
  "required": ["week_id"]
}
```

**Result**: `{"ok": true, "recorded": {"cooked": [...], "skipped": [...]}}` — or
`ok: false` with `unknown_week` / `unknown_meal_name` / `already_recorded` errors.

---

## 3. `propose_plan` (client, `strict: true`)

Registers a structured draft plan for the session. Input is the full **WeeklyPlan
payload** defined in [`weekly-plan.schema.json`](./weekly-plan.schema.json) (declared
with `strict: true` and `additionalProperties: false` throughout). The tool runs the
deterministic validators and, on success, stages the draft and returns the computed
grocery/bill preview so the agent can check budget fit before presenting the plan.

**Input schema**: the `WeeklyPlan` object from `weekly-plan.schema.json` (single
top-level parameter set — the plan fields are the tool input).

**Result (valid plan)**

```json
{
  "ok": true,
  "staged": true,
  "estimated_bill_usd": 74.50,
  "budget_delta_usd": -5.50,
  "grocery_item_count": 23
}
```

`budget_delta_usd` is `null` when no budget is set; positive means overage (the agent
must state the amount and offer adjustments per FR-020 — an over-budget plan is
staged, not rejected, because nutrition outranks budget per FR-008).

**Result (invalid plan)** — `ok: false`; `staged: false`; error codes the validators
emit:

| Code | Rule |
|---|---|
| `dinner_count_out_of_range` | dinner_count not in 3–4 (FR-004) |
| `lunch_count_out_of_range` | lunch_count not in 0–7 |
| `meal_count_mismatch` | `len(meals) != dinner_count` |
| `batch_meal_count` | not exactly one batch meal (FR-005) |
| `stretch_meal_count` | not exactly one stretch meal (FR-006) |
| `batch_stretch_same_meal` | batch and stretch flags on the same meal |
| `batch_coverage_mismatch` | `lunches_covered != lunch_count` or `total_portions` wrong (FR-005/014) |
| `technique_not_new` | stretch technique already in cooked history (FR-006) |
| `repeated_dish` | normalized name cooked within 4 weeks, no repeat request / relaxation (FR-023); message lists the offending names |
| `missing_field` / `invalid_value` | protein / prep_minutes / servings / ingredient constraint failures |

The agent is expected to self-correct and re-propose; validation failures are never
shown raw to the user.

---

## 4. `accept_plan` (client)

Persists the currently staged draft as the week's plan (upsert on `week_id` — an
accepted plan edited mid-week is re-proposed and re-accepted, FR-015/022). Returns
the final artifacts for presentation.

**Input schema**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "week_id": { "type": "string", "description": "Must match the staged draft's week_id." }
  },
  "required": ["week_id"]
}
```

**Result**

```json
{
  "ok": true,
  "week_id": "2026-W30",
  "grocery_list": {
    "items": [
      {
        "name": "chicken thighs",
        "quantities": [{ "amount": 1.5, "unit": "lb" }],
        "estimated_price_usd": 7.5
      }
    ],
    "estimated_total_usd": 74.5,
    "budget_delta_usd": null
  },
  "meals_logged": 4,
  "instructions_needed": ["Braised short ribs", "Miso cod"]
}
```

`instructions_needed` lists, in plan order, the display names of every accepted meal
with no `source_url` — the worklist for `save_meal_instructions` (FR-010a). It is the
only signal that makes the "recipe link *or* authored instructions, never neither"
guarantee actionable: `propose_plan` cannot enforce it, because a draft meal with no
`source_url` is indistinguishable from one whose steps are coming at acceptance.

Errors: `no_staged_draft` (nothing proposed this session), `week_mismatch`,
`week_already_final` (attempting to edit a past week).

The grocery list is computed by `services/grocery.py` (deterministic merge — SC-003);
the agent renders it for the phone but must not alter items or totals.

---

## 5. `save_meal_instructions` (client)

Stores authored cooking steps for one meal of an accepted week (FR-010a/010b), so the
cookbook can return them later.

**Input schema**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "week_id": { "type": "string", "description": "The accepted week the meal belongs to." },
    "meal_name": { "type": "string", "description": "The meal's name as it appears in the plan." },
    "steps": {
      "type": "array",
      "items": { "type": "string" },
      "description": "The cooking steps in order, one string per step, unnumbered. Steps only — never restate ingredients."
    }
  },
  "required": ["week_id", "meal_name", "steps"]
}
```

**Result**: `{"ok": true, "week_id": "2026-W31", "meal_name": "Braised short ribs"}` —
`meal_name` echoes the plan's display name, since the lookup normalizes. Errors:
`unknown_week`, `unknown_meal_name`.

Idempotent: re-saving overwrites. **The week's status is irrelevant** — steps stay
writable after a week goes `final`, which is what lets the cookbook author them on
demand for earlier weeks. Do not mirror `accept_plan`'s `week_already_final` guard
here.

---

## 6. `get_meal_instructions` (client)

Reads a meal's stored steps plus the context needed to present them (FR-010b).

**Input schema**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "meal_name": { "type": "string", "description": "The dish to look up." },
    "week_id": {
      "type": ["string", "null"],
      "description": "The week to read from. Omit to resolve the most recent week containing this dish."
    }
  },
  "required": ["meal_name"]
}
```

**Result**

```json
{
  "ok": true,
  "week_id": "2026-W31",
  "meal_name": "Chicken chili",
  "instructions": "Brown the chicken over medium heat.\nAdd the tomatoes and simmer.",
  "ingredients": [
    { "name": "ground chicken", "quantity": 1.0, "unit": "lb", "estimated_price_usd": 6.0 }
  ],
  "source_url": null
}
```

`ingredients` come from the meal on the week's stored `plan_json`, never from the
`meals` row — they are not duplicated into the instructions text.

**`instructions: null` is a success, not an error**: the meal exists but has no steps
yet, and the agent is expected to author them and call `save_meal_instructions` with
the `week_id` returned here. A dish that appears in no week is `ok: false` with
`unknown_meal_name`. Collapsing the two would break the unusable-link path (FR-010c).

Without `week_id`, resolution is a policy rather than a key lookup: the same dish
cooked in two weeks can carry different steps, so the most recent week containing it
wins.

---

## 7. `web_search` (server-side)

Declared as `{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}` in
the tool list. Executed on Anthropic's infrastructure — no client implementation.
Used for recipe sourcing during curation and for user-requested dish lookups
(FR-010); result citations supply `source_url` on web-sourced meals. If search fails
or returns nothing usable, the system prompt directs the agent to fall back to its
own knowledge and continue (spec edge case) — the session never fails on search
unavailability.

---

## Session-level behavioral contract

- The runner handles `stop_reason: "pause_turn"` (server-tool pause) by restarting
  with the paused turn appended, capped at 5 restarts (research R6).
- The system prompt + tool list form the stable cached prefix; per-turn content never
  precedes them (research R12).
- One `propose_plan`/`accept_plan` cycle per user-visible plan revision; the agent
  must call `get_meal_history` before its first proposal of a session and must run
  the cooked check-in (via `record_cooked_checkin`) before curating when
  `pending_checkin_week_id` is non-null (FR-021).
- After every successful `accept_plan`, the agent must call `save_meal_instructions`
  once per name in `instructions_needed` (FR-010a). The steps do not go in the chat
  message — the plan message stays scannable and the steps surface from the cookbook
  when the user is ready to cook.
