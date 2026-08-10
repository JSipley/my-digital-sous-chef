# Feature Specification: Weekly Dinner Planner

**Feature Branch**: `001-weekly-dinner-planner`

**Created**: 2026-07-18

**Status**: Draft

**Input**: User description: "Purpose: A conversational agent that plans a week of dinners for the user to cook at home. It exists to help them build culinary skills and spend less on eating out by making home cooking easy to plan and execute. Core function: Curates 3–4 healthy, high-protein dinners per session (athlete-focused, no formal macros; some nights left open), including one big-batch meal-prep dish reheated through the week and one flagged \"stretch\" meal introducing a new technique. Prioritization: Nutrition > budget > prep time > skill-building. Artifacts (per plan): Flat grocery list, estimated weekly grocery bill, prep time, serving sizes. Budget: Optional monthly grocery budget; agent plans an estimated weekly bill down from it (no per-meal caps). Memory/history: No pre-loaded cookbook; logs meals week to week to avoid repetition and reference past plans. Per-session config: Diet type and number of servings."

## Clarifications

### Session 2026-07-18

- Q: What surface does the user converse with the meal-planning agent on? → A: A bot on an existing messaging platform (specific platform selected during planning).
- Q: For the 4-week no-repeat rule, when do two meals count as the same main dish? → A: Same named dish (chicken chili twice = repeat; chicken chili then beef chili = allowed).
- Q: After a weekly plan is accepted, how do mid-week changes and re-planning work? → A: One plan per week, editable until the week ends; history records only the final state.
- Q: How does a meal get counted as cooked in history? → A: Next-session check-in — the agent asks which of last week's planned meals were actually cooked; only cooked meals count toward repetition avoidance and technique history, and skipped meals may be re-proposed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Plan a Week of Dinners and Lunches Conversationally (Priority: P1)

The user starts a planning session and tells the agent how many dinners and how many lunches they want to cook this week — the only required input. They then converse with the agent until they have an accepted plan of healthy, high-protein dinners. The plan always includes exactly one big-batch meal-prep dish, cooked once and portioned to cover every requested lunch of the week plus one dinner night, and exactly one meal flagged as a "stretch" meal that introduces a cooking technique the user has not used before. Remaining nights of the week are left open. The user may volunteer preferences such as diet type or serving counts at any point in the conversation, but is never required to provide them. Each meal shows its estimated prep time and serving size. The user can reject or swap any proposed meal during the conversation before accepting the plan.

**Why this priority**: This is the product. Without conversational curation of a weekly plan, no other capability has anything to attach to. It alone delivers the core value: a week of home cooking planned in minutes.

**Independent Test**: Can be fully tested by running a first-ever session (no history, no budget), providing only a dinner count and a lunch count, and verifying the accepted plan contains the requested number of dinners with the batch meal (covering all lunches plus one dinner) and stretch meal correctly flagged, plus prep time and serving size on every meal — with no other input demanded.

**Acceptance Scenarios**:

1. **Given** a new planning session, **When** the user states how many dinners and lunches they want to cook this week, **Then** the agent proposes that many dinners — each labeled with estimated prep time and serving size — without requiring any further input.
2. **Given** a proposed weekly plan, **When** the user reviews it, **Then** exactly one meal is flagged as the big-batch meal-prep dish (stating that it covers all of the week's lunches plus its dinner night) and exactly one different meal is flagged as the stretch meal (with the new technique named).
3. **Given** a proposed plan, **When** the user rejects one meal, **Then** the agent replaces only that meal with an alternative that still satisfies the requested meal counts, any stated preferences, and the healthy/high-protein criteria.
4. **Given** a session where the user has not yet said how many dinners and lunches they want, **When** the user asks for a plan, **Then** the agent asks for the missing counts before proposing meals.
5. **Given** the user states a diet type or serving count mid-conversation, **When** the plan is next proposed or revised, **Then** every meal reflects the stated preference without the session restarting.
6. **Given** any proposed meal, **When** the user asks why it was chosen, **Then** the agent explains the choice in terms of the priority order: nutrition first, then budget, then prep time, then skill-building.

---

### User Story 2 - Get a Grocery List and Estimated Bill (Priority: P2)

Once the user accepts a weekly plan, the agent produces a single flat grocery list — all ingredients across all meals merged into one list with combined quantities scaled to each meal's serving size — together with an estimated total grocery bill for the week.

**Why this priority**: The grocery list and bill are what turn a plan into action at the store. They are the first artifacts the user touches after planning, and the bill estimate is a prerequisite for budget-aware planning (User Story 3).

**Independent Test**: Can be tested by accepting any plan and verifying the grocery list contains every ingredient required by the plan's meals exactly once (duplicates merged, quantities combined) and that a single estimated total bill is presented.

**Acceptance Scenarios**:

1. **Given** an accepted weekly plan, **When** the user requests the grocery list, **Then** the agent produces one flat list where each ingredient appears once with a combined quantity covering all meals that use it.
2. **Given** an accepted plan, **When** the grocery list is generated, **Then** ingredient quantities reflect each meal's serving size, including the batch meal's portions for every lunch it covers plus its dinner night.
3. **Given** a generated grocery list, **When** the user views it, **Then** an estimated total weekly grocery bill accompanies the list.
4. **Given** an accepted plan, **When** the user swaps a meal afterward, **Then** the grocery list and estimated bill are regenerated to match the updated plan.

---

### User Story 3 - Plan Within a Weekly Grocery Budget (Priority: P3)

At the beginning of the planning conversation, the agent gives the user the chance to set a weekly grocery budget for the plan; providing one is optional. When a budget is set, the agent curates plans whose estimated weekly bill fits it. There are no per-meal price caps — only the weekly total matters. If nutrition needs and the budget conflict, the agent favors nutrition (per the priority order) and clearly tells the user the estimated bill exceeds the budget and by how much.

**Why this priority**: Budget awareness sharpens the "spend less on eating out" goal, but plans are still valuable without it — which is why the budget is optional.

**Independent Test**: Can be tested by setting a weekly budget at the start of a session, requesting a plan, and verifying the estimated weekly bill is at or below the budget — or, when that is infeasible, that the overage is explicitly surfaced with adjustment options.

**Acceptance Scenarios**:

1. **Given** a new planning session, **When** the conversation begins, **Then** the agent offers the option to set a weekly budget, and declining does not block or delay planning.
2. **Given** the user declines to set a budget, **When** they plan the week, **Then** planning proceeds normally and the estimated bill is presented without any budget comparison.
3. **Given** the user sets a weekly grocery budget at the start of the conversation, **When** the plan is created, **Then** the plan's estimated bill is at or below that budget.
4. **Given** a budget is set and the cheapest plan meeting nutrition standards still exceeds it, **When** the plan is presented, **Then** the agent states the overage amount and offers adjustments that reduce cost without compromising nutrition.
5. **Given** a budget was set earlier in the session, **When** the user changes or removes it before accepting the plan, **Then** the plan and its budget comparison update to the new value (or to no budget) without restarting the session.

---

### User Story 4 - Remember Past Weeks and Avoid Repetition (Priority: P4)

Every accepted plan is logged to the user's meal history. At the start of the next session, the agent briefly checks in on which of last week's planned meals were actually cooked; only cooked meals count toward repetition avoidance and technique tracking, and skipped meals can be offered again. In later sessions the agent uses this history to avoid re-proposing recently cooked meals, and the user can ask about past weeks ("what did I cook two weeks ago?") or recall a past favorite ("put that chili back in this week"). There is no pre-loaded cookbook — the agent's knowledge of the user's meals comes entirely from this accumulated history.

**Why this priority**: Variety and recall compound the product's value over weeks of use, but the first several sessions are fully useful without history.

**Independent Test**: Can be tested by accepting plans in two consecutive weeks and verifying week two proposes no main dish from week one, then asking the agent to list week one's meals and to re-add one of them.

**Acceptance Scenarios**:

1. **Given** an accepted plan, **When** the session ends, **Then** the plan's meals are logged to history with the week they belong to.
2. **Given** meals logged in recent weeks, **When** a new plan is curated, **Then** no main dish cooked in the previous 4 weeks repeats unless the user explicitly asks for a repeat.
3. **Given** a previous week's plan exists, **When** the user starts a new session, **Then** the agent asks which of that week's meals were cooked before curating, and a meal marked as skipped may appear in the new plan.
4. **Given** logged history, **When** the user asks what they cooked in a past week, **Then** the agent accurately lists that week's meals.
5. **Given** logged history, **When** the user asks to repeat a specific past meal, **Then** the agent includes it in the current plan and it counts toward the requested dinner count.
6. **Given** a first-ever session with no history, **When** a plan is curated, **Then** planning proceeds without error, no repetition check is applied, and no cooked check-in occurs.

---

### Edge Cases

- User requests fewer than 3 or more than 4 dinners: the agent explains the 3–4 range and asks the user to choose within it (open nights absorb the difference).
- User requests zero lunches for the week: the batch meal still appears but is portioned for its dinner night only, and the agent notes the reduced meal-prep benefit.
- User requests more lunches than there are days in the week: the agent explains the limit and asks for a count of 7 or fewer.
- Diet type makes high-protein harder (e.g., vegan): the agent adapts protein sources to the diet rather than declining, and says how protein is being covered.
- The batch meal and stretch meal cannot be the same dish; if only 3 meals are planned, two of the three carry the flags.
- Weekly budget is too low to meet nutrition standards for the week's meals: nutrition wins, the overage is stated plainly with the amount, and cost-saving adjustments are offered.
- All reasonable candidate meals were cooked within the 4-week repetition window: the agent relaxes the window (oldest repeats first) and tells the user it is doing so, rather than failing.
- User changes serving count after accepting a plan: meals stay, but serving sizes, grocery quantities, and the estimated bill are recalculated.
- User abandons a session before accepting a plan: nothing is logged to history and no artifacts are produced.
- User skips or cannot recall the cooked check-in for last week: the agent treats all of that week's planned meals as cooked and moves on without blocking the session.
- Plan generation takes noticeable time: the agent acknowledges the request immediately and indicates it is working, rather than going silent.
- The agent cannot produce a plan satisfying all constraints (meal counts + stated preferences + budget + repetition): it states which constraint it could not satisfy and asks the user which one to relax, instead of returning nothing.
- Web recipe search is unavailable or returns nothing usable: the agent falls back to proposing meals from its own knowledge and continues the session rather than failing.

## Requirements *(mandatory)*

### Functional Requirements

**Session & Curation**

- **FR-001**: The system MUST conduct planning as a conversation in which the user can request a plan, ask questions, reject or swap individual meals, and accept the final plan.
- **FR-002**: The system MUST collect the number of dinners and the number of lunches the user wants to cook for the week at the start of each planning session, prompting for whichever is missing before proposing meals. No other input is required to begin planning.
- **FR-003**: The system MUST accept optional preferences — such as diet type or serving counts — stated at any point in the conversation and apply them to the current plan without restarting the session. When no diet type is stated, meals assume no dietary restriction; when no serving count is stated, each meal defaults to a single serving.
- **FR-004**: The system MUST curate the user's requested number of dinners per weekly plan, within a range of 3 to 4, leaving the remaining nights of the week open. Lunches are not separately curated dishes; every requested lunch is covered by the batch meal.
- **FR-005**: Each plan MUST include exactly one big-batch meal-prep dish, flagged as such, cooked once and portioned to serve as one of the week's dinners plus every lunch the user requested, with the number of lunches it covers stated.
- **FR-006**: Each plan MUST include exactly one "stretch" meal, distinct from the batch meal, flagged as such, that introduces a cooking technique not present in the user's cooked meal history, with the technique named. A technique from a planned-but-uncooked stretch meal still counts as new and may be reintroduced.
- **FR-007**: All curated meals MUST be healthy and high-protein in an athlete-oriented sense, described qualitatively (primary protein source identified per meal) without formal macro or calorie tracking.
- **FR-008**: When curation involves trade-offs, the system MUST resolve them in this priority order: nutrition first, then budget, then prep time, then skill-building — and MUST be able to explain a meal choice in those terms when asked.
- **FR-009**: When the user rejects a meal, the system MUST replace only that meal, and the replacement MUST satisfy all session constraints (requested meal counts, stated preferences such as diet type or servings, nutrition standard, weekly budget if set, repetition rules).
- **FR-010**: The system MUST be able to search the web for recipes, both to source candidate meals during curation and when the user asks for a specific dish; when a proposed meal is based on a recipe found on the web, the system MUST share the recipe's source alongside the meal, labelled as a recipe.
- **FR-010a**: Every meal of an accepted plan MUST be actionable by exactly one of two paths and never neither: it carries a web recipe source (FR-010), or the system MUST author and store step-by-step cooking instructions for it. Acceptance MUST return the list of meals lacking a recipe source so the instructions are written rather than left to chance, and a meal that still ends up with neither MUST produce instructions on demand when the user asks for them.
- **FR-010b**: Stored cooking instructions MUST be retrievable both conversationally ("how do I make the chili?") and from a dedicated browsing surface (FR-026a). Instructions MUST be presented with the meal's ingredients and quantities first, then numbered steps. Ingredients are read from the stored plan and MUST NOT be duplicated into the stored instructions.
- **FR-010c**: When the user reports a recipe source as unusable (paywalled, dead, unhelpful), the system MUST author and store instructions for that meal, which then carries both a source and stored instructions.

**Plan Artifacts**

- **FR-011**: For every accepted plan, the system MUST produce a single flat grocery list in which each ingredient appears exactly once with quantities merged across all meals and scaled to each meal's serving size, including the batch meal's full lunch-and-dinner coverage.
- **FR-012**: For every accepted plan, the system MUST present an estimated total weekly grocery bill.
- **FR-013**: Every meal in a plan MUST display an estimated prep time.
- **FR-014**: Every meal in a plan MUST display its serving size, and the batch meal MUST display its total portions across the lunches and the dinner night it covers.
- **FR-015**: When a plan changes after artifacts are generated (meal swap, serving change), the system MUST regenerate the grocery list and estimated bill to match.

**Budget**

- **FR-016**: The system MUST offer the user the option to set a weekly grocery budget at the beginning of each planning conversation. Providing one is optional: declining MUST NOT block or delay planning, and the user MAY set, change, or remove the budget at any point before the plan is accepted.
- **FR-017**: The weekly budget applies only to the current week's plan; the system MUST NOT carry it forward to later weeks or track spending across weeks.
- **FR-018**: When a weekly budget is set, the system MUST curate plans whose estimated weekly bill fits within it.
- **FR-019**: The system MUST NOT apply per-meal price caps; budget conformance is evaluated only against the weekly total.
- **FR-020**: When the estimated bill exceeds the weekly budget, the system MUST state the overage amount and offer cost-reducing adjustments that do not lower the plan's nutrition standard.

**Memory & History**

- **FR-021**: The system MUST log every accepted plan's meals to the user's meal history as planned, associated with the week they were planned for; abandoned (unaccepted) sessions MUST NOT be logged. At the start of the next planning session, the system MUST ask which of the previous week's planned meals were actually cooked and record each meal's cooked status; if the user skips or cannot answer the check-in, all planned meals are treated as cooked.
- **FR-022**: Each week has exactly one plan, which remains editable (meal swaps, serving changes, full re-plan) until that week ends; history records only the week's final state, and superseded versions MUST NOT count toward repetition rules.
- **FR-023**: The system MUST NOT propose a main dish that was cooked in the previous 4 weeks of history, unless the user explicitly requests a repeat or the system has announced it is relaxing the window for lack of alternatives. Two meals count as the same main dish only when they are the same named dish (e.g., "chicken chili" twice is a repeat; "chicken chili" followed by "beef chili" is not); variety across similar dishes remains a soft curation goal, not a blocking rule. Meals planned but not cooked do not block re-proposal and MAY be offered again.
- **FR-024**: The system MUST answer user questions about past weeks' plans from history and MUST allow a past meal to be recalled by reference into the current plan.
- **FR-025**: The system MUST NOT rely on any pre-loaded cookbook or recipe database of the user's meals; its record of what the user has cooked comes only from accumulated history. Meal ideas themselves MAY come from the agent's own knowledge or from web recipe search.

**Conversation Experience**

- **FR-026**: The system MUST deliver the conversation and all plan artifacts as messages through a bot on an existing messaging platform, formatted so the grocery list and plan are readable on a phone (including while shopping).
- **FR-026a**: The system MUST provide a cookbook surface that lists an accepted week's meals, one row per meal, showing for each whether it has a recipe source, stored instructions, or neither, and offering a direct way to pull up the instructions. The surface MUST open on the current week and MUST allow walking back through earlier weeks that have accepted plans. Cookbook rows and the actions attached to them MUST derive from the same stored plan, so an action always returns the meal on the row it belongs to.
- **FR-027**: While generating a plan or artifacts, the system MUST acknowledge the request immediately and indicate that work is in progress rather than remaining silent.
- **FR-028**: When the system cannot satisfy all constraints simultaneously, it MUST state which constraint failed and what the user can do next (e.g., relax budget, allow a repeat), never returning an empty or unexplained result.

### Key Entities

- **Weekly Plan**: One week's accepted plan; carries the week it belongs to, the requested dinner and lunch counts, any preferences stated during the session (diet type, serving counts), the weekly budget if one was set, flags identifying the batch meal and stretch meal, and its generated artifacts (grocery list, estimated bill).
- **Meal**: A single dish in a plan; has a name, primary protein source, estimated prep time, serving size, optional flags (batch with its lunch-and-dinner coverage, stretch with named technique), and an optional source link when based on a recipe found on the web.
- **Grocery List**: The flat, merged list of ingredients for an accepted plan; each entry has an ingredient name and combined quantity; owns the estimated total weekly bill.
- **Budget**: The user's optional weekly grocery amount, offered at the start of the planning conversation; applies only to the current week's plan and is not carried across weeks.
- **Meal History**: The chronological log of accepted plans' meals by week, each meal carrying a planned/cooked status set by the next session's check-in; the sole source of "what the user has cooked" for repetition avoidance, stretch-technique novelty, and recall.
- **Session Configuration**: The per-session required dinner and lunch counts, plus any optional preferences (diet type, serving counts, weekly budget) stated during the conversation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from starting a session to an accepted plan with grocery list and estimated bill in under 10 minutes of conversation.
- **SC-002**: 100% of accepted plans contain the requested number of dinners (within the 3–4 range), exactly one flagged batch meal covering every requested lunch plus one dinner night, exactly one flagged stretch meal (distinct from the batch meal), and prep time and serving size on every meal.
- **SC-003**: 100% of generated grocery lists contain every ingredient required by the plan's meals, with no ingredient listed more than once.
- **SC-004**: Across any 4 consecutive weeks of use, no cooked main dish is re-proposed unless the user requested it or the system announced a window relaxation.
- **SC-005**: When a weekly budget is set, 90% of accepted plans have an estimated bill at or below it; the remaining cases explicitly state the overage amount.
- **SC-006**: After 8 weeks of weekly use, the user has been introduced to at least 8 distinct new cooking techniques via stretch meals.
- **SC-007**: The agent begins visibly responding to any user message within 5 seconds, and a complete draft weekly plan is presented within 30 seconds of the user supplying their dinner and lunch counts.
- **SC-008**: A first-time user completes their first full planning session without external instructions, guided entirely by the conversation.

## Assumptions

- The product serves a single user (personal tool); multi-user accounts and shared plans are out of scope.
- The conversation happens through a bot on an existing messaging platform; which platform is a planning-phase decision. Interaction is text-message based, so rich UI (buttons, screens) is not assumed, and the constitution's visual-UI provisions apply only to the extent the chosen platform allows message formatting.
- The plan covers the week's dinners and lunches; every lunch is supplied by the single batch meal rather than by separately curated dishes. Breakfast, snacks, and meals on open nights are out of scope.
- "Flat grocery list" means one consolidated, unsectioned list with duplicates merged — not grouped by recipe (grouping by store aisle or category is not required).
- The repetition-avoidance window defaults to 4 weeks and applies to main dishes, not individual ingredients.
- The weekly budget, when provided, is treated as covering the groceries this product plans for that week; there is no monthly budget and no tracking of spending across weeks.
- The batch meal and the stretch meal are always two different dishes.
- Grocery bill figures are good-faith estimates based on typical grocery prices, not live prices from a specific store; no store integration is in scope.
- Meal history persists indefinitely across sessions; cooked status is captured by the next session's check-in, and an unanswered check-in defaults every planned meal to cooked.
- Diet type is optional (e.g., omnivore, pescatarian, vegetarian); when none is stated no dietary restriction is assumed, and when one is stated the agent adapts protein sources to it rather than refusing any particular diet.
- Unless the user specifies serving counts, each meal is planned at a single serving (the product serves one person), and the batch meal at one portion per covered lunch plus its dinner night.
- Meal ideas come from the agent's own knowledge and from recipes it finds by searching the web; no licensed or pre-imported third-party recipe database is required.
