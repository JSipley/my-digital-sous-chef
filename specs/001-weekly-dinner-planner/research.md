# Research: Weekly Dinner Planner

**Feature**: `001-weekly-dinner-planner` | **Date**: 2026-07-18

Every "NEEDS CLARIFICATION" from the plan's Technical Context draft is resolved below.
Format per decision: what was chosen, why, and what else was evaluated.

## R1. Messaging platform → Telegram Bot API

**Decision**: Deliver the bot on **Telegram** via the official Bot API, connected by
**long polling**.

**Rationale**: The spec (clarification session) defers the platform choice to planning
and requires a bot on an existing messaging platform, phone-readable output, and
progress indication. Telegram is the strongest fit for a personal, single-user bot:
bot creation is instant and free (BotFather), there is no business-verification or
approval process, long polling removes any need for a public HTTPS endpoint (the bot
can run on a home machine), `sendChatAction("typing")` natively supports the FR-027
"working on it" signal, and MarkdownV2 formatting renders well on phones for the
grocery-list-while-shopping case (FR-026). Mature async Python support exists
(python-telegram-bot).

**Alternatives considered**:
- **Discord** — good bot API, but server/channel model is awkward for a 1:1 personal
  assistant and the mobile UX is gaming-oriented.
- **Slack** — workspace administration overhead and free-tier message history limits
  for a single-person tool.
- **WhatsApp** — Business Platform requires Meta approval, a hosted endpoint, and
  per-conversation pricing; poorest fit for a hobby-scale personal bot.
- **Signal** — no official bot API; community bridges (signal-cli) are fragile.
- **SMS (Twilio)** — per-message cost, no rich formatting, poor list rendering.

The platform sits behind the `bot/` package boundary; a later port to another platform
touches only that package.

## R2. Language/runtime → Python 3.12+

**Decision**: Python 3.12+, `src/` layout, single package `sous_chef`.

**Rationale**: First-class Anthropic SDK support (including the beta tool runner used
for the agent loop), the most mature Telegram bot framework, Pydantic for typed
validation of the plan payload, and a pytest ecosystem that satisfies the
constitution's test-first mandate cheaply. Single-user workload has no throughput
requirement that would motivate another runtime.

**Alternatives considered**: TypeScript/Node (equivalent SDK support; rejected to keep
one language across bot, validation logic, and tests with the strongest data-validation
story via Pydantic). Go/Rust (no productivity payoff at this scale).

## R3. Telegram framework → python-telegram-bot v22

**Decision**: `python-telegram-bot` v22 (async), long polling via
`Application.run_polling()`.

**Rationale**: De-facto standard, actively maintained, typed, async — integrates
cleanly with the async Anthropic SDK; handles retries/backoff against the Telegram API.

**Alternatives considered**: `aiogram` (comparable; smaller English-language
ecosystem), raw HTTP against the Bot API (reinvents update polling, retry, and
dispatch for no benefit).

## R4. LLM → Claude Sonnet 5 (`claude-sonnet-5`) via the Anthropic Python SDK

**Decision**: `claude-sonnet-5` with adaptive thinking (`thinking: {"type": "adaptive"}`),
`output_config.effort` tuned per call (default `medium`; conversational turns that
don't touch `propose_plan` may drop to `low` after measurement), streaming enabled,
prompt caching on the stable system prompt. The model ID lives in `config.py` so it is
a one-line swap.

**Rationale**: This is a single-user hobby bot calling the API on every turn of every
session, indefinitely — token cost compounds in a way raw capability doesn't need to
justify. Sonnet 5 handles the curation task's multi-constraint reasoning (nutrition >
budget > prep time > skill-building, plus repetition rules and per-session
preferences) comfortably: the hard rules are enforced by deterministic validators
(R7), not model judgment, so the model's job is proposing a plausible plan and
conversing, not guaranteeing correctness — exactly the workload Sonnet-class models
are priced and sized for. Opus would add cost on every turn for reasoning headroom
this task doesn't consume, since `propose_plan` rejection + self-correction already
covers the cases where a weaker model gets the structured output wrong. Adaptive
thinking replaces deprecated `budget_tokens`; sampling parameters (`temperature` etc.)
are not sent (removed on this model family). Streaming + prompt caching serve the
SC-007 latency budget (5 s visible response, 30 s draft plan) and further cut
per-turn token cost by reusing the cached system-prompt/tool-list prefix.

**Alternatives considered**: `claude-opus-4-8` (stronger reasoning ceiling, but at
multiples of the token cost for a task whose correctness is already backstopped by
deterministic validators; kept as a config-swap upgrade path if real usage shows
Sonnet-quality curation is unsatisfying), `claude-haiku-4-5` (cheapest, but weakest
fit for multi-constraint curation quality — risks more `propose_plan` rejection
round-trips, which would spend the token savings on retries), self-hosted open models
(operational burden far beyond a personal tool).

## R5. Web recipe search → Anthropic server-side `web_search_20260209` tool

**Decision**: Declare the server-side web-search tool
(`{"type": "web_search_20260209", "name": "web_search"}`) in the agent's tool list.

**Rationale**: FR-010 requires web recipe search with source attribution. The
server-side tool needs no extra vendor account, no scraping code, and returns results
with citations, which directly supplies the "share the recipe's source" requirement.
The `_20260209` variant's dynamic filtering keeps token cost down. Fallback behavior
(edge case: search unavailable/no results) is handled in the system prompt: propose
from own knowledge and continue.

**Alternatives considered**: Brave Search/SerpAPI + fetching (second API key, HTML
extraction pipeline, more failure modes), no search at all (violates FR-010).

## R6. Agent loop → Anthropic SDK beta tool runner

**Decision**: `client.beta.messages.tool_runner(...)` with `@beta_tool`-decorated
client tools plus the raw server web-search tool definition, wrapped in the documented
`pause_turn` restart pattern (mirror history, restart the runner with the paused turn
appended, capped restarts).

**Rationale**: The runner removes hand-written loop code (constitution: simplest
structure) while still exposing every hook needed here (the tools themselves are the
control points). The `pause_turn` wrapper is required because the Python runner does
not auto-resume server-tool pauses.

**Alternatives considered**:
- **Manual agentic loop** — more code to maintain and test for no added control we need.
- **Managed Agents** — hosted sessions/containers are overkill for a self-hosted
  single-user bot and add a beta control-plane dependency.
- **Claude Agent SDK** — a coding/filesystem agent harness; wrong tool surface for a
  conversational domain agent.

## R7. Structured plan output → strict tool use + deterministic validators

**Decision**: The agent registers a draft via the `propose_plan` client tool declared
with `strict: true` and a schema with `additionalProperties: false` everywhere
([contracts/weekly-plan.schema.json](./contracts/weekly-plan.schema.json)). The
payload is parsed into Pydantic models, then passed through deterministic validators
in `services/plan_validator.py` that enforce what the schema cannot: dinner count in
3–4, lunch count 0–7, exactly one batch meal and one distinct stretch meal, batch
portions = lunches + 1 dinner, stretch technique not in cooked history, no cooked main
dish repeated within 4 weeks (unless explicitly requested/relaxed), budget comparison.
Validation failures return as the tool result so the model self-corrects before the
user ever sees an invalid plan.

**Rationale**: Strict tool use guarantees schema-valid JSON; hard business rules
(SC-002/SC-004) must not depend on model compliance, so they live in ordinary tested
code. Note: strict schemas do not support numeric range constraints — ranges are
enforced by the validators, which is where we want them anyway.

**Alternatives considered**: `output_config.format` JSON responses (forces the whole
reply to be JSON, killing the conversational text channel), free-text parsing
(fragile, untestable), trusting the model to follow rules stated in the prompt
(unverifiable; violates testability of SC-002/SC-004).

## R8. Storage → SQLite (stdlib `sqlite3`)

**Decision**: One SQLite file (path from config). Two tables: `plans` (week_id PK,
status, full plan JSON, artifacts JSON, timestamps) and `meals` (normalized rows:
week_id, name, normalized_name, role flags, technique, cooked_status) to support the
4-week repetition query, technique history, and past-week recall without JSON
scanning. No ORM; a small `history_repo.py` owns all SQL.

**Rationale**: Single user, tiny data, zero operational burden, durable across
restarts, real queries for the history features. Stdlib means no dependency.

**Alternatives considered**: JSON files per week (awkward window queries, torn-write
risk), PostgreSQL (server to run for ~52 rows/year), an ORM (indirection with no
payoff at two tables).

## R9. Grocery list + bill → deterministic merge over structured ingredients

**Decision**: Every meal in a proposed plan carries structured ingredients
(`name`, `quantity`, `unit`, `estimated_price_usd`). `services/grocery.py` merges them
deterministically: names normalized (casefold, trim, singularize simple plurals);
quantities summed when units are convertible within a family (mass g/kg/oz/lb; volume
ml/l/tsp/tbsp/cup; count); non-convertible quantities for the same ingredient render
as one line with compound quantity ("2 cups + 1 can"). Batch-meal quantities are
already scaled by the model to full lunch+dinner coverage and re-checked by the
validator against `total_portions`. The estimated bill is the sum of item price
estimates — the model supplies good-faith per-ingredient prices (per spec assumption:
typical prices, no store integration); the total and any budget overage math are
computed in code, never generated as text.

**Rationale**: SC-003 (every ingredient exactly once, duplicates merged) and FR-015
(regeneration on change) must be provable by unit tests. Keeping prices as model
estimates but totals as code keeps the "good-faith estimate" flexibility while making
budget comparisons (FR-018/FR-020) exact.

**Alternatives considered**: Letting the model write the grocery list text (duplicate
merging unverifiable), a real price API (no store integration in scope per spec).

## R10. Repetition window → SQL over cooked history + announced relaxation

**Decision**: "Same named dish" = case-/whitespace-insensitive match on normalized
meal name (per clarification: chicken chili twice = repeat; beef chili ≠ chicken
chili). The validator rejects any proposed main dish whose normalized name appears
with `cooked_status = cooked` in the previous 4 ISO weeks, unless (a) the user
explicitly requested the repeat (flag on the proposal) or (b) the session has entered
announced-relaxation mode. Relaxation is agent-initiated per the edge case: when the
validator keeps rejecting for repetition, the system prompt instructs the agent to
tell the user it is relaxing the window (oldest first) and set the relaxation flag.

**Rationale**: Exact-name matching implements the clarified rule with zero ambiguity
and is trivially testable (SC-004). Softer similarity ("variety across similar
dishes") stays a curation goal in the prompt, not a blocking rule — exactly as FR-023
specifies.

**Alternatives considered**: Embedding/fuzzy similarity matching (contradicts the
clarified same-named-dish rule and adds nondeterminism).

## R11. Week identity & lifecycle → ISO week in a configured timezone

**Decision**: Weeks are identified by ISO-8601 week strings (`2026-W30`, Monday
start), computed in a configured IANA timezone (env `SOUS_CHEF_TZ`, default the
user's local zone). A plan is `accepted` and editable while its week is current;
when a session starts in a later week, prior plans are treated as `final` and the
cooked check-in targets the most recent final week not yet checked in.

**Rationale**: FR-022 ("editable until the week ends; history records only the final
state") needs an unambiguous week boundary; ISO weeks give one, and lazy finalization
(on next session start) avoids any background scheduler.

**Alternatives considered**: Rolling 7-day windows (ambiguous "week end"), a cron
finalizer (extra moving part; lazy evaluation is sufficient).

## R12. Responsiveness strategy (SC-007, FR-027)

**Decision**: On every incoming message the bot immediately (before any LLM call)
sends `sendChatAction("typing")` and, for plan-generation requests, a short ack
message ("On it — pulling your plan together…"). The typing action is refreshed every
~4 s while the agent works. Draft-plan latency is managed by streaming, prompt caching
(stable system prompt + tool definitions first, volatile content last), and effort
tuning. An integration test asserts ack-before-agent-call ordering; a marked live
test measures the 30 s draft budget.

**Rationale**: Telegram's typing indicator expires after ~5 s, so refresh is needed
for long generations. Caching the large stable prefix cuts both latency and cost on
every turn of a session.

**Alternatives considered**: Editing a placeholder message with progressive content
(more moving parts; can be added later without design change).

## R13. Testing strategy → fake LLM transport + contract pinning

**Decision**: Three layers.
1. **Unit** — pure functions in `services/` (merge, bill, validators, weeks,
   repetition) with nominal/boundary/error cases.
2. **Contract** — the tool schemas generated by `@beta_tool` and the Pydantic plan
   model are asserted equal to the checked-in contract files (`contracts/`), so any
   drift fails review (constitution II: contract change requires test change).
3. **Integration** — a `fake_llm.py` transport implements the same interface as the
   agent client and replays scripted tool-call transcripts (e.g. "call propose_plan
   with this payload, then emit this text"). Each spec acceptance scenario maps to
   one test that drives the real session loop, tools, services, and SQLite (temp
   file), with zero network. Live-API smoke tests are marked `live` and excluded by
   default.

**Rationale**: The constitution demands deterministic, order-independent,
network-free tests; the LLM is the only nondeterministic component, so it is the one
thing faked. Everything the spec measures (counts, flags, merging, repetition,
overage messages) is downstream of the tool boundary and therefore fully exercised.

**Alternatives considered**: Recorded-cassette LLM responses (brittle to prompt
changes), testing only services without the session loop (misses FR-001/FR-028
conversation behavior).

## R14. Lint/format/type/CI → ruff + mypy + GitHub Actions

**Decision**: `ruff` for linting and formatting (zero-warning gate), `mypy` on
`src/` (strict-ish: `disallow_untyped_defs`), GitHub Actions workflow running ruff,
mypy, and pytest on every PR (red pipeline blocks merge per constitution).

**Rationale**: Single fast tool for lint+format satisfies Principle I's zero-warning
requirement; typing pays for itself at the tool-payload boundary.

**Alternatives considered**: black+flake8+isort (three tools where one suffices),
pyright (fine, but mypy integrates with Pydantic's plugin ecosystem).
