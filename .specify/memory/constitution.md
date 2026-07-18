<!--
Sync Impact Report
==================
Version change: [template] → 1.0.0 (initial ratification)
Modified principles: n/a (initial adoption)
Added sections:
  - Core Principles (I. Code Quality; II. Testing Standards; III. User Experience
    Consistency; IV. Performance Requirements)
  - Quality Gates
  - Development Workflow
  - Governance
Removed sections: none (template placeholders replaced)
Templates requiring updates:
  - ✅ .specify/templates/plan-template.md (Constitution Check gates made concrete)
  - ✅ .specify/templates/tasks-template.md (test tasks changed from OPTIONAL to
    MANDATORY per Principle II)
  - ✅ .specify/templates/spec-template.md (no changes needed — mandatory Success
    Criteria section already satisfies Principles III & IV)
  - ✅ .specify/templates/checklist-template.md (no changes needed)
Follow-up TODOs: none
-->

# My Digital Sous Chef Constitution

## Core Principles

### I. Code Quality

Code is read far more often than it is written; this project optimizes for the reader.

- All code MUST pass automated linting and formatting checks before merge, with zero
  warnings. Tooling is configured in Phase 1 (Setup) of every feature and enforced in CI.
- Every module, function, and variable MUST have a name that states its purpose without
  requiring a comment. Comments are reserved for constraints the code cannot express.
- Each function and module MUST have a single responsibility. Cyclomatic complexity
  above 10 in any function MUST be refactored or explicitly justified in the plan's
  Complexity Tracking table.
- Dead code, commented-out blocks, and speculative abstractions (YAGNI violations) MUST
  NOT be merged. Start with the simplest structure that satisfies the feature.
- Every change MUST be reviewed before merge. Reviewers verify adherence to this
  constitution, not only functional correctness.

**Rationale**: A recipe assistant will grow through many small features (search, meal
planning, substitutions). Consistent, simple code keeps each increment cheap to add and
safe to change.

### II. Testing Standards (NON-NEGOTIABLE)

Test-first development is mandatory. Tests are written, reviewed, and observed to fail
before implementation begins (Red-Green-Refactor).

- Every user story MUST have integration tests derived from its acceptance scenarios
  before implementation of that story starts.
- Every public API, service contract, or shared schema MUST have contract tests. A
  contract change without an accompanying test change MUST be rejected in review.
- Business logic (e.g., ingredient scaling, substitution rules, meal-plan generation)
  MUST have unit tests covering nominal cases, boundary conditions, and error paths.
- The full test suite MUST pass before merge. Skipped, disabled, or flaky tests are
  treated as failures: they MUST be fixed or removed, never ignored.
- Tests MUST be deterministic and independent of execution order, network availability,
  and wall-clock time unless the test explicitly exercises those concerns.

**Rationale**: Test-first forces testable design and turns acceptance scenarios into
executable specifications, which is the backbone of the spec-driven workflow this
project uses.

### III. User Experience Consistency

Every user-facing surface behaves as one coherent product, not a collection of features.

- All UI components MUST come from a single shared design system or component library.
  One-off variants of existing components MUST NOT be introduced without amending the
  design system itself.
- Domain terminology MUST be consistent across every screen, message, and document:
  one term per concept (e.g., "recipe", "ingredient", "meal plan") with no synonyms in
  user-facing text.
- Every user-facing flow MUST define its loading, empty, and error states in the
  feature spec before implementation. Errors shown to users MUST state what happened
  and what the user can do next.
- Interactive elements MUST give visible feedback within 100 ms of user input, even
  when the underlying operation takes longer (progress indicators, optimistic updates).
- All UI MUST meet WCAG 2.1 AA accessibility: keyboard navigable, screen-reader
  labeled, and color-contrast compliant.

**Rationale**: Cooking is a hands-busy, attention-split context. A predictable,
accessible interface with clear feedback is a functional requirement, not polish.

### IV. Performance Requirements

Performance budgets are defined up front and enforced as acceptance criteria, not tuned
after the fact.

- Every feature spec MUST include measurable performance criteria in its Success
  Criteria section. When a feature does not state its own numbers, these defaults
  apply and are enforceable:
  - API/backend operations: p95 latency < 200 ms under expected load.
  - Search and filtered queries (recipes, ingredients): results in < 500 ms.
  - Initial screen/page load: interactive in < 2 s on median target hardware.
  - UI interaction feedback: < 100 ms (see Principle III).
- Changes that regress a stated budget MUST NOT merge without a documented exception
  in the plan's Complexity Tracking table, including the remediation plan.
- Resource-intensive work (image processing, large imports, external API calls) MUST
  be asynchronous or streamed; the UI thread and request path MUST NOT block on it.
- Performance-sensitive paths identified in a plan MUST have automated checks
  (benchmark, load test, or budget assertion) before the feature is considered done.

**Rationale**: Fixed budgets defined at spec time make performance testable and prevent
slow accretion of latency across releases.

## Quality Gates

These gates apply to every feature and are checked in the plan's Constitution Check
before Phase 0 research and re-checked after Phase 1 design:

- **Simplicity gate**: The plan uses the simplest project structure that satisfies the
  feature. Added projects, layers, or patterns are justified in Complexity Tracking.
- **Test-first gate**: tasks.md orders test tasks before implementation tasks within
  every user story phase, and each acceptance scenario maps to at least one test.
- **UX gate**: User-facing features specify loading, empty, and error states, use
  design-system components, and use canonical domain terminology.
- **Performance gate**: Success Criteria include measurable performance numbers, or the
  constitution defaults are explicitly adopted in the spec.

A feature that cannot pass a gate MUST record the violation and justification in the
plan's Complexity Tracking table or be revised until it passes.

## Development Workflow

- Features follow the Spec Kit flow: constitution → specify → clarify → plan → tasks →
  implement. Artifacts live under `specs/<###-feature-name>/`.
- Work proceeds in priority order (P1 → P2 → …). Each user story MUST be independently
  implementable, testable, and demonstrable before the next story begins.
- CI MUST run linting, formatting, and the full test suite on every pull request; a red
  pipeline blocks merge with no manual overrides.
- Reviews verify constitution compliance explicitly. A reviewer who approves a change
  that violates a principle without a recorded justification shares responsibility for
  the violation.
- Commits are small and scoped to a task or logical group of tasks from tasks.md.

## Governance

- This constitution supersedes all other development practices in this repository.
  Where guidance conflicts, the constitution wins.
- **Amendments**: Any contributor may propose an amendment via pull request modifying
  this file. The PR MUST state the motivation, the exact text change, and the migration
  impact on existing templates and specs. Amendments merge only after review approval.
- **Versioning**: The constitution version follows semantic versioning. MAJOR for
  backward-incompatible removals or redefinitions of principles; MINOR for new
  principles or materially expanded guidance; PATCH for clarifications and wording
  fixes. Every amendment updates the version line and the Sync Impact Report.
- **Compliance review**: Every plan's Constitution Check and every pull request review
  MUST verify compliance with the current version. Recurring violations of the same
  principle SHOULD trigger either stricter tooling or an amendment — the constitution
  is kept honest by use, not exceptions.

**Version**: 1.0.0 | **Ratified**: 2026-07-18 | **Last Amended**: 2026-07-18
