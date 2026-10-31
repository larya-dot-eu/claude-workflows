# Claude Planning - Implementation Workflows and Best Practices

> **Invoke this skill at the start of any new feature, integration, or implementation session.**
> **Approval is explicit.** A phase is not approved until the user writes a clear confirmation (e.g. "approved", "looks good", "proceed").
> Work through every phase in order. Do not skip phases. Do not proceed past an exit gate until it is explicitly cleared.
> **Gate marker:** end every message that reaches an exit gate with the line `[[gate P<n>]]` (n = the phase number). The `wf` plugin (`/wf on`) uses it to move to the next phase when the user approves.
>
> **This is the full reference.** For everyday use, keep [`Claude-Workflows-Best-Practices-Compact.md`](./Claude-Workflows-Best-Practices-Compact.md) loaded as the always-on spine and read the matching section here when you enter a phase or need a full checklist — that keeps token cost and drift down on long sessions.
>
> **Running on Superpowers?** Its skills hand off to each other on their own, and several of those handoffs skip a gate below. The *Superpowers:* notes in each phase say where; [Running on Superpowers](#running-on-superpowers-checked-against-v701) at the end collects them as one list you can paste into `CLAUDE.md`.
>
> **Sync rule:** this file and the compact spine are one spec in two forms. Any change to phases, gates, or checklists must land in both files in the same commit — a commit touching only one of them is the drift signal to look for in review.

---

## Task Tiers — pick before anything else

Not every change earns the full pipeline. Name the tier you believe applies and let the user confirm it before starting:

- **Full (default):** anything feature-shaped — new behavior, touches data boundaries, auth, schema, external services, or more than a couple of files. Run every phase in order.
- **Quick (small, bounded changes):** a typo fix, a config tweak, a doc edit, an obvious one-file bug fix. Skip Phases 1–6. Instead:
  1. State the blast radius — every file and caller the change touches, verified by opening them (for a bug fix, grep the callers of the function you're touching; the root-cause fix lives where all callers route through).
  2. Make the change, with a test where the logic is non-trivial.
  3. Verify with a real run, not by reading the diff.
  Before step 2, move off the starting branch (feature branch or worktree) — Quick skips Phase 6, which is where Full creates its isolated workspace, so Quick must do it here.
  Phases 8–10 still apply when the change ships: the deploy gates are never skipped — only the planning phases are.
- **Bug fixes and spikes on Superpowers.** "Fix this bug" routes to `systematic-debugging` before anything else, with no brainstorming and no worktree; a brainstorming *spike* skips plan, implementation and review by design. Both still go through the tier check and get a branch first — before `systematic-debugging` adds any instrumentation or test; re-check the tier once it finds the root cause (outside the blast radius → Full). A spike stays throwaway and never merges — keeping it is a new request through the Full tier.
- **Opting out of questions is not a tier.** Superpowers `brainstorming` treats a fully specified request as a "quick, clear task" and offers "just dive in" when you didn't ask for it. Neither one skips the tier check: name the tier and get it confirmed anyway.
- **Escalation rule:** if a "quick" change grows — it touches a file you didn't name in the blast radius, raises a design question, or crosses a data boundary — stop and restart in the full tier. When unsure, default to full.

---

## Prerequisites — Load Before Starting

Before Phase 1, load the following into context:

- **`CLAUDE.md`** — architecture rules, stack conventions, coding patterns, explicit constraints, what NOT to do. If missing, stop and ask the user before continuing.
- **`ROADMAP.md`** — current project state, priorities, already-decided directions. *Optional:* many projects have none — if absent, note that in your summary and continue; do not block on it.
- **Relevant existing code** — any files, modules, or APIs the planned work touches or must follow. If you cannot locate the code the work touches, stop and ask.

After loading, summarize to the user:
- What you understand about the current project state
- Which architectural patterns and conventions apply to this session
- Any prior decisions that are relevant

Do not proceed to Phase 1 until the user confirms your summary is correct or provides corrections.

---

## Phase 1 — Context Priming

Confirm your working model of the project before any exploration begins.

State explicitly:
- The current relevant architecture and patterns
- Known constraints from `CLAUDE.md` and `ROADMAP.md`
- Stack conventions (integration patterns, external services, APIs, databases)
- Any prior decisions relevant to this session

**Exit gate:** Ask the user: *"Is this an accurate picture of the project context? Anything to correct or add before we explore the problem?"*
Do not proceed to Phase 2 until the user confirms.

**Superpowers:** `brainstorming` reads the project before its first message and plays the request back. That first message **is** the Prerequisites + Phase 1 summary — don't produce a second one. It must name the `CLAUDE.md` constraints and prior decisions that apply, and the user's confirmation or correction of it clears this gate.

---

## Phase 2 — Exploration (PM Mode)

**Exploration skill:** mandatory before any creative work — new features, components, functionality, or behavior changes. Default to the **superpowers** `brainstorming` skill for this phase. With it not installed, run the exploration questions below by hand.

Your role in this phase is to ask clarifying questions only. Do not propose solutions. Do not write specs. Do not suggest implementations.

Ask the user to define:
- **The why:** What problem does this solve? Why now?
- **The constraints:** Technical, time-based, dependency-based
- **What makes this case different:** How does this deviate from existing patterns in the codebase?

While exploring, surface:
- Ambiguities and unstated assumptions
- Which parts of the existing codebase are affected
- Anything in the existing code that complicates the request
- **Prior solutions already in the codebase** — search for existing implementations of this same *kind* of problem (similar functions, components, data flows, CSS/utility classes). List every candidate, even partial matches. If none exist, say so explicitly — absence established by searching, not assumed.

**Exit gate (hard stop):** Before proceeding to Phase 3, you must be able to answer all three:
1. What is the exact problem being solved?
2. What are the constraints?
3. What makes this case different from existing patterns?

If you cannot answer all three clearly — stay in Phase 2 and ask the user for the missing clarity.

**Superpowers:** brainstorming's questions and playback chunks are this phase. It may offer proposals the user can correct — allowed only as marked guesses about *what* they want, never *how* to build it. Brainstorming moves on to *Lay out the approaches* once it feels it understands; **before** that message, state the three exit answers above plus the prior-solution search result. The approaches message is the first act of Phase 3.

---

## Phase 3 — Spec Writing

Write a spec that covers:
- Behavior and expected outcomes
- Interfaces: inputs, outputs, APIs, data shapes
- Edge cases and error states
- **Transactional integrity** — for any multi-step write (especially across tables or services), state whether it must be atomic (all-or-nothing). If a partial failure would leave data inconsistent, say so and require it run in a single transaction; if eventual consistency is acceptable, say that explicitly.
- Assumptions you are making — state them explicitly
- **Access-control matrix** (see below) — who is allowed to do and see what
- **Expected scale** (see below) — the load this is designed to survive
- **Reuse** — name the existing functions, components, modules, or styles this builds on instead of re-implementing. If the work is genuinely net-new, state why nothing existing fits.
- **Presentation vs. logic** — any value a designer or you would tweak without touching logic (colors, fonts, spacing, copy strings, thresholds, feature flags) belongs in CSS/theme/config, never hardcoded inline. If no config point exists yet for it, creating one is part of the change.

### Access-Control Matrix (security-relevant expected behavior)

Most security holes you introduce are not bad code — they are you not knowing the *expected* access rules for this app. Surface those rules now so you and every future session act on them instead of guessing.

For each role or user type (anonymous, authenticated user, admin, service), state:
- Which resources/records it may **read**
- Which it may **create / modify / delete**
- What scopes it to *its own* data (the ownership key — usually a user/tenant UUID enforced at the database layer, e.g. row-level security)

Produce this matrix as a required spec output, and mirror it into `CLAUDE.md` in Phase 9 so it persists across sessions. If the feature touches no data boundaries, write "no access boundaries" explicitly — do not leave it blank.

If the feature involves auth tokens or sessions, also ask the user explicitly: **if a credential is compromised (stolen JWT or session), must it be revocable instantly?** If yes, the spec needs a revocation path — a server-side denylist, or short-lived tokens plus a refresh mechanism — because token expiry alone is not revocation. If instant revocation is not required, record that decision so a later session doesn't assume it exists.

### Expected Scale (load the design must survive)

Code that works for one user in a demo is not code that survives real traffic — and the schema, query, and state decisions that decide this are made *here*, not patchable at deploy. State the target so the design is built for it, not retrofitted:

- **Traffic:** expected and peak requests/sec; concurrent users.
- **Data volume:** rows in the hot tables now and after a year of growth; which tables grow unbounded.
- **Access shape:** the few queries on the hot path (these need indexes); any query that scans or joins large tables.
- **State:** where per-user/session state lives — it must be in the database or a shared store, **not** in process memory, or a second server (or a restart) loses it.

If real load is genuinely unknown, state an explicit assumed target (e.g. "design for 100 req/s, 100k rows") rather than leaving it open — a named number is what Phase 5 and Phase 10 test against. Carry this into `CLAUDE.md` in Phase 9 alongside the access-control matrix.

### Transition Checkpoint Before Phase 4

Before writing any plan, run this check against the codebase:

> - Do any proposed APIs or types conflict with existing code?
> - Is anything in the spec assumed without being verified against the actual codebase?

Report your findings explicitly to the user. Do not summarize as "looks good." If conflicts or unverified assumptions exist, fix the spec before proceeding.

**Exit gate:** The spec is verified against the codebase. No unresolved conflicts. No unverified assumptions. User has approved the spec.

**Superpowers:** brainstorming's design doc **is** this spec. Its default outline (intent, goals/non-goals/anti-goals, constraints, approaches, decided how, left to builder) has no slot for the access-control matrix, expected scale, transactional integrity, reuse or presentation-vs-logic — add them, to the short design doc for a "small change" too (one line each, or "N/A — why"). Run the Transition Checkpoint above **before** asking for approval of the doc: after approval, brainstorming's hard gate goes straight to `writing-plans` and nothing else, so a checkpoint placed after it never runs. Its builder-check subagent (projects only — small changes get none) is a useful extra pass but not a substitute — it only asks what a builder would need, not who may read whose records.

### Output Format

One required output, one optional companion — saved to your spec directory, e.g. `docs/specs/`, or `docs/superpowers/specs/` if you run the [superpowers](https://github.com/obra/superpowers) plugin (if `CLAUDE.md` names a different path, use that). Choose once per project and write the choice into `CLAUDE.md`:

- **Local only (gitignored):** never committed. A git worktree is a fresh checkout and **does not contain gitignored files**, so every later reference to the spec or plan (the plan's `**Spec:**` line, skill and subagent hand-offs) must be an **absolute path** into the main checkout. A relative path silently resolves to nothing inside the worktree, and the executor then rules on conflicts without the spec.
- **Committed:** commit on the **feature branch**, after it exists — never on the branch the session started on. Superpowers' own default is "committed", and brainstorming runs before any worktree exists, so without this rule it commits the design doc to the default branch.

**1. Markdown spec (required — for Claude):**
`YYYY-MM-DD-[feature-name]-spec.md` (Superpowers names it `YYYY-MM-DD-<topic>-design.md` — either is fine; be consistent) — structured prose with headers covering behavior, interfaces, edge cases, transactional integrity, assumptions, the access-control matrix, and the expected-scale target. This is what future sessions read — and what Phase 4 builds the plan from: spec first, plan derived from it.

**2. HTML visual companion (optional — generate only when the user asks for it, never unprompted):**
`spec-[feature-name].html` — self-contained styled file generated from the same content. Must include:
- Sticky sidebar navigation linking to each section
- Color-coded sections: behavior (blue), interfaces (green), edge cases (amber), assumptions (red), access-control matrix (purple), expected scale (teal)
- All assumptions highlighted with a visible warning style
- A checklist of exit gate items the user can tick off while reviewing

> Ask the user how they want to view the HTML. If they have local browser access, just open the file. If the project runs on a remote/headless host, serve it: run `python3 -m http.server 8090` from the project root and open `http://<host>:8090/<spec-path>/spec-[feature-name].html` from a machine that can reach it (LAN, SSH tunnel, or a mesh VPN like Tailscale). Kill with Ctrl+C when done.

---

## Phase 4 — Plan Writing

Break the verified spec into ordered, executable steps.
Build verification in from the start, not bolt it at the end.

**Planning skill:** default to the **superpowers** `writing-plans` skill for this phase. If it is not installed, fall back to **gstack** (`/plan`, or `/plan-eng-review` / `/plan-devex-review` for a review pass). With neither installed, follow the step structure below by hand.

Each step must include:
- What code changes or actions are required
- The exit state after this step — is the codebase in a consistent or broken state between steps?
- How this step will be verified

The plan as a whole must also carry:
- **Global Constraints that carry the spec's rules verbatim** — the access-control matrix, the expected-scale target, the reuse list, and the presentation-vs-logic rule. When tasks are run by subagents (Superpowers `subagent-driven-development`), the implementer sees its own task text plus Global Constraints (and whatever the controller chooses to add), and the reviewer sees the same plus the diff. Neither reads the spec. A rule not copied here does not exist during implementation.
- **An Ownership map, inside Global Constraints** — one owner per domain fact (which type/table/module holds it); one home per kind's traits; module import direction; the error type that crosses each boundary; and runtime flow — which component handles each event and where state lives over time. Tasks cite its rows instead of each redefining the fact. It goes **inside Global Constraints**, not as a separate section before Task 1: Superpowers' `task-brief` copies an implementer's brief from its `Task N` heading to the next one, so text before Task 1 reaches no implementer — only Global Constraints are carried into every dispatch. Per-task interface blocks only check that neighbours agree; without this map, two tasks that need the same fact each define it, and nobody sees it until the final review ([superpowers#2587](https://github.com/obra/superpowers/issues/2587)).

### Transition Checkpoint Before Phase 5

After writing the plan, run these five questions against it. Answer each one with specific findings — not "yes":

> 1. Is verification built in at each step, not just at the end?
> 2. Are tasks and steps grouped by what is independently vs. dependently testable?
> 3. Did you extract everything relevant from the codebase and the conversation — constraints, limitations, non-obvious edge cases?
> 4. Are there external dependencies — APIs, file paths, database states, service availability — that the plan assumes exist but does not verify first?
> 5. Which claims are most likely wrong — and did you verify each against the actual source? This includes an empty grep, a green suite that never exercises the changed path, a silent log, or anything the plan marked "most likely wrong" or "verify on contact".

Fix any issues found before proceeding.

**Exit gate:** All five questions answered with concrete findings. All issues resolved. User has approved the plan.

**Superpowers:** `writing-plans` ends by asking which execution method to use (subagent-driven or native), and both executors then run every task without pausing. Answer "not yet": the Phase 4 checkpoint, Phase 5 and Phase 6 come first, and the execution method is chosen at the end of Phase 6. Its built-in Self-Review is confirmatory ("fix inline, no need to re-review") — it is not the checkpoint above and not Phase 5.

### Output Format

One required output, one optional companion — saved to your plans directory, e.g. `docs/plans/`, or `docs/superpowers/plans/` if you run the superpowers plugin (stored the same way as the spec — local-only with absolute paths, or committed on the feature branch; see Phase 3 Output Format. If `CLAUDE.md` names a different path, use that):

**1. Markdown plan (required — for Claude):**
`YYYY-MM-DD-[feature-name]-plan.md` — ordered steps with exit states and verification methods. This is what future sessions execute from.

**2. HTML visual companion (optional — generate only when the user asks for it, never unprompted):**
`plan-[feature-name].html` — self-contained styled file generated from the same content. Must include:
- Sticky sidebar navigation with phase links
- Color-coded phases: exploration (purple), spec (blue), plan (green), review (red), TDD (orange), implementation (teal)
- Each plan step as a card with: step number, action, exit state, verification method
- The dependency graph rendered as an inline SVG diagram
- Checkpoint questions rendered as a visible checklist the user ticks off before approving
- External dependencies called out in a highlighted warning box

---

## Phase 5 — Adversarial Review

Switch from generation mode to review mode. Your goal is to break the plan, not defend it.

**Who runs it.** The author of a plan reviewing it in the same context shares its blind spots. Scale the review to the risk, so the cost stays proportional:
- **Full tier, small plan (≤ 5 tasks), no data boundary:** inline in this session.
- **Larger, or touching auth, schema, money or external services:** dispatch **one** fresh-context subagent on the most capable model with the spec and plan paths and the checklist below. It reports findings; you route them with the loop-back table. One review seat, not a per-task loop.

Check:
- Trace each step's intermediate state: after this step, is the codebase consistent or is it broken between steps?
- Draw the actual dependency graph: what must already exist before each step can run?
- What did you observe in the codebase that is not yet documented in the plan?
- **Absence is not confirmation.** An empty grep, a green suite that never exercises the changed path, a missing file, a silent log — each means "unverified," not "safe." If a search returns nothing, widen it (wrong file, wrong name, wrong dir) and open the actual source before concluding the thing is absent or fine. Never infer a signature or behavior from a sibling's usage when you can read the definition.
- **Re-attack the plan's own flagged risks first.** Any claim the plan marked "most likely wrong" or "verify on contact" gets opened and confirmed against source in *this* review — it is the first thing to break, not the thing deferred to execution.
- **Run an abuse-case pass against the access-control matrix.** The checks above attack correctness; now attack security. For each endpoint or data path the plan touches, ask how an attacker abuses it: Can one user reach another user's records by changing an ID (IDOR)? Is the ownership rule enforced at the database (row-level security), or only in app code that a crafted request skips? Can a protected route be hit unauthenticated, or an admin route reached by header/path tricks? Is any input trusted before server-side validation? Every "allowed" cell in the matrix needs a plan step that enforces it; every gap is a finding.
- **Run a scale pass against the expected-scale target.** Now attack load. Take the Phase 3 numbers and ask what melts at peak ×10: Does a hot-path query run without an index, or scan/join a large table? Will a table grow unbounded with no archival or pagination? Is any per-user/session state held in process memory, so it breaks the moment there's a second replica or a restart? Is the schema shaped for the demo (the convenient join) rather than the access pattern? Each one is a design finding to fix in the plan now — these do not patch cleanly after the schema and traffic are real.
- **Dry-run every command the plan names.** Run each distinct test, build and lint command once against the real repo, in the environment the plan says (e.g. `pytest --collect-only`, `vitest run --passWithNoTests`, the venv the plan activates). Don't reason about whether a flag exists — run it. Wrong flags, wrong working directory and missing environment activation fail on the first command of execution, and a self-review that only reads the plan passes them every time.
- **Run a design-shape pass against the Ownership map.** Per-task interface checks prove neighbours agree; they don't prove the design is one design. Check the plan text for: a fact with more than one owner; an optional field for a fact its kind always has; a kind's traits split across modules; code branching on a kind's name instead of reading the kind's record; an untyped/stringly error crossing a boundary; a new module with no stated import direction; an event with no single handler, or state whose home over time is unstated. Each is an architectural finding (→ Phase 3 if the spec's model is wrong, → Phase 4 if only the plan's).
- **Run a reinvention-and-hardcoding pass.** Does any step write logic the codebase already has — the reuse candidates from Phase 2/3? Reuse them or state why not. Does any step hardcode a color, copy string, threshold, or flag that belongs in CSS/theme/config? Each is a finding: route to Phase 4 to reroute through the existing code or a config point. This is a design finding — cheaper here than after the code is written.

### Loop-Back Decision

| Finding | Action |
|---|---|
| Surface fix — wrong step order, missing verification point | Return to Phase 4 and fix the plan |
| Architectural issue — wrong interface, broken dependency, broken intermediate state | Return to Phase 3 and fix the spec |
| Fundamental problem — wrong approach or wrong problem being solved | Return to Phase 2 and re-explore |

**Rollback rule:** If more than one-third of all steps of the plan need reworking, do not patch. Restart from Phase 3.

**Exit gate:** The plan is structurally sound. No broken intermediate states. Dependency order is correct. All assumptions are surfaced and verified. User has approved.

---

## Phase 6 — TDD Planning

Do not start this phase until Phase 5 is complete and the plan is structurally sound. Designing tests against a broken plan wastes the work.

**Isolation first.** Create the isolated workspace now, at the start of Phase 6 — not in Phase 7. This phase writes test files into the real suite; done on the starting branch, those files land on it. Use the **superpowers** `using-git-worktrees` skill or a feature branch by hand. Declare the preference in `CLAUDE.md` so the skill doesn't ask, and close its three escape hatches:
- it prefers the harness's native worktree tool over `.worktrees/` — fine, use whichever it picks;
- if `.worktrees/` isn't gitignored it adds it to `.gitignore` **and commits that on the current branch** — set this up once through a normal PR instead, or have it stop and ask;
- if worktree creation is blocked (sandbox) it "works in the current directory" — stop and ask instead.

**Resuming:** a fresh session (after `/clear` or a Phase 9 hand-off) starts in the main checkout. Check `git worktree list` and enter this plan's existing worktree; never create a second one from the default branch.

**Committed specs/plans:** if you chose to commit them (Phase 3 Output Format), move the spec and plan from the main checkout into the worktree now, commit them there, and delete the main-checkout copies — otherwise two copies drift.

Define before writing any implementation code:
- What interface changes are needed? (concrete function/method signatures, input contracts, APIs, return types/shapes)
- Which behaviors must be tested first? (critical paths, complex logic, integration points)
- Can each component be designed for testability? (inject dependencies, return results instead of side effects, no hidden state)
- Architectural testability: Can each component have a deep module design (small interface, rich hidden logic)?
- Are dependencies injected?
- Are functions pure/returning results rather than relying on hidden side effects?
- Path coverage breakdown: Map out the test matrix per component across:
  * Happy Path (nominal baseline)
  * Sad/Error Path (explicit domain errors, failed validations, thrown exceptions)
  * Edge/Boundary Path (empty sets, min/max limits, zero/null values)
- Mocking strategy: Keep tests social where possible; only mock non-deterministic elements (time, UUIDs) and external I/O boundaries (network, databases). Do not mock domain logic.

Output a prioritized list of behaviors to test with interface definitions agreed.

### Output Format

Do not create a new TDD document, and do not append the output as a separate section at the end of the plan. Superpowers' `task-brief` cuts each implementer's brief from its `Task N` heading to the next one: text before Task 1 reaches no implementer, and a trailing `## TDD` section is glued onto the **last** task's brief only. Write the output where it will be read:

- **Interface definitions + Prioritized Test Matrix** — into the existing Phase 4 plan file (`<plans-dir>/YYYY-MM-DD-[feature-name]-plan.md`): interfaces into the Ownership map (in Global Constraints) and the owning tasks' Interfaces blocks; each behavior in the matrix as a test step inside the task that owns the code:
  * Concrete type signatures and data models.
  * Numbered, ordered list of behaviors using the ZOMBIES progression (Zero/One/Many/Boundaries/Exceptions).
  * Categorization tag for each behavior: `[Happy]`, `[Sad]`, `[Edge]`.

- **Failing test stubs for the top 3 critical behaviors** — write these directly into the project's test suite (e.g. `tests/`, `backend/tests/`):
  * The top 3 tests must not all be happy paths: include at least 1 nominal path and 1 error/boundary path.
  * Structure each test strictly using AAA (Arrange, Act, Assert).
  * Use clear descriptive naming: `should_[expected_behavior]_when_[state_or_condition]`.
  * Ensure the code compiles/parses, but the test assertion fails cleanly on behavior (`AssertionError` / failed expectation, NOT an unhandled runtime syntax crash).
  * **Running on Superpowers executors:** once RED is confirmed, copy each stub's code verbatim into its owning task's "write the failing test" step, then remove the stub files — do **not** commit them ahead of their tasks. A red test sitting in the suite before its task stalls execution: the worktree baseline check stops on failing tests, `task-done` refuses to record any task whose suite is red, implementers run the full suite and chase failures they don't own, and the per-task review diff no longer contains the test that drives it. Moved into the task, the stub becomes that task's own RED → GREEN.

**Exit gate:** 
1. Interface design and test order agreed with user.
2. The 3 test stubs are written in the real test runner and confirmed to be in a legitimate RED state (failing on assertion, not syntax) — and, on Superpowers executors, moved into their owning tasks.
3. Strictly zero implementation/production code written yet.
4. Execution method chosen (Superpowers: subagent-driven or native) — this is where `writing-plans`' handoff question gets answered.
5. User says to start Phase 7. Approving the plan (Phase 4) or this phase's test design is not a go to execute: if an execution method was preset, `writing-plans` treats "plan approved" as the signal to start.

---

## Phase 7 — TDD Implementation

**Isolation:** the isolated workspace from Phase 6 must exist — confirm you are in it before the first task (the **superpowers** executors check this themselves via `using-git-worktrees`). Do not implement directly on the branch you started the session on.

**Execution skill:** drive this phase with a plan-execution + TDD process. Public options that implement this discipline: the **superpowers** skills (`subagent-driven-development` — a fresh implementer and a fresh reviewer per task; `executing-plans` — "native": you implement every task in this session, one fresh reviewer on the whole branch at the end; `executing-plans` loads `test-driven-development` for the Red→Green→Refactor loop; `subagent-driven-development` does not — its implementers follow TDD only if the task's steps say so, so every task keeps explicit "write failing test → run, see it fail" steps), or **gstack** (`/spec`, `/ship`). The per-feature plan names which; with neither installed, run the Red→Green→Refactor loop below by hand.

Work in vertical slices. Complete one slice fully before starting the next.

For each slice:
1. Write one failing test — RED. The test defines the expected behavior.
2. Write the minimal code to make it pass — GREEN. No extra logic.
3. Refactor if needed — improve structure without changing behavior.
4. Move to the next slice.

### Scope Creep Rule

Do not:
- Refactor code not directly related to the current slice
- Add features or improvements you notice along the way
- Extend the plan unilaterally

If you spot something that should be changed, say:
> *"I noticed [X] while implementing this slice. I have noted it as a separate task and am continuing with the current slice."*

**Regression rule:** If a green cycle causes a previously passing test to fail, stop immediately. Do not continue to the next slice. Surface the regression to the user and decide: fix now or revert the slice.

**Superpowers executors don't stop for this on their own.** `subagent-driven-development` and `executing-plans` run "rulings, not stalls": they decide conflicts and plan defects themselves, write a `Ruling:` line to their ledger and keep going, and stop only for an irreversible action, a security-sensitive action, an outside side effect (merge, push, publish), or a hopelessly broken plan. Put these additional stop conditions in `CLAUDE.md` (user instructions outrank skills):
- a previously passing test fails (the regression rule above);
- a ruling would change the access-control matrix, the schema, a public interface, or the scale design;
- a task needs to touch a file outside the plan's file map (the scope-creep rule above).
Everything else stays a ruling — that keeps the speed the executors are built for.

**Structural checkpoint after core tasks.** If early tasks build abstractions that later tasks depend on, run one whole-branch structural review (design-shape checklist from Phase 5, against the code) right after those tasks and before the dependents start. Per-task reviewers see one diff each, so a fact defined twice across tasks is invisible to them until the final review — after later tasks have copied it.

**Before the workspace is deleted.** When their final review is clean, Superpowers executors delete the plan's workspace, including the ledger. They do list every ruling in their final chat message — but chat doesn't survive compaction or a new session. Copy the ledger's `Ruling:`, `parked`, `minor (deferred)` and "no reachable spec" lines into the plan file under `## Execution record` first (commit it if plans are committed); Phase 8 needs them.

**Exit gate:** All plan steps implemented. All tests passing. No unplanned changes introduced. Execution record saved.

---

## Phase 8 — Post-Implementation Review

Check:
- Did the implementation match the plan? If not, document what changed and why.
- Did any new constraints or patterns surface that should be added to `CLAUDE.md`?
- Did any edge cases appear during implementation that were not in the spec?
- Did the implementation duplicate logic that already existed elsewhere, or inline a value that belongs in config? Duplication is often only visible once the code is written.
- Does `ROADMAP.md` need updating if direction shifted?

**Every ruling in the Execution record is a divergence.** For each one, state: *matches spec* / *spec updated* / *reverted*. A plan executed by Superpowers can look like it matched while the executor quietly decided a dozen things on your behalf.

If no divergence from the plan is found (zero rulings in the Execution record, and nothing else diverged), state that explicitly ("no divergence found") rather than leaving it implied by silence — an unstated "no issues" and an unchecked item look identical in a log.

Report findings to the user. Flag any recommended doc updates.

**Rollback signal:** If the implementation diverged significantly from the plan without documented reasoning, treat this as a signal that the spec or adversarial review was insufficient. Note this for the next planning session.

**Exit gate:** Findings reported. Doc updates flagged or completed. User sign-off received. If significant divergence was found, trigger a Phase 9 update immediately before closing Phase 8 — do not defer to the next session.

---

## Phase 9 — Living Document Update

After each phase and after every major step, update:
- **Work plan document** — what is done, what changed, what is next
- **`CLAUDE.md`** — if new patterns or constraints were established during this session, and the **access-control matrix** and **expected-scale target** from Phase 3 (write both in as first-class sections, not passing notes — this is the expected-behavior and load context that stops the next session from re-introducing access holes or demo-shaped, non-scaling decisions)
- **`ROADMAP.md`** — if priorities or direction shifted

### Session Checkpoint Rule

You cannot reliably measure your own context window, so do not wait for a percentage. Checkpoint on observable triggers instead — whenever any of these occur:

- an exit gate is cleared (the phase's results are final — capture them now)
- the harness warns that context is running low, or compacts/summarizes the conversation
- the user says the session is getting long, or hands off to another session

Say:
> *"Checkpointing the living work plan now so this session can be resumed without loss."*

Write the update so that a fresh session with no conversation history can resume work immediately from the document alone.


---

## Phase 10 — Deployment & Release

Mistakes are very expensive.
This is the most important step in preventing self-inflicted product outages.
Verification is not just testing. Implementation passing tests is NOT done. A deploy is the highest-blast action in the workflow — treat it as such.

- **Prove a deployable artifact before deploying.** Build and boot the real artifact locally (e.g. `docker build` + run, hit `/health` and the expected routes) before pushing to prod. Production must never be the first place a build runs.
- **Pass the security gate before deploying — run it against that local boot.** Same rule as everything else here: produce evidence from real requests, not "should be fine." Skip a row only if it genuinely doesn't apply to this change (no SQL, no auth cookies, or the Phase 3 access-control matrix says that boundary doesn't exist) — and name which row and why.
  - **Auth:** an unauthenticated request to a protected endpoint returns `401`/`403`, not `200` with data. Confirm with a real authless request, not by reading the code.
  - **Session cookies:** auth/session cookies are set `HttpOnly` (JavaScript can't read them, so XSS can't steal them), `Secure` (HTTPS only), and `SameSite`. Confirm on the actual `Set-Cookie` response header, not from config.
  - **Ownership / IDOR:** acting as user A, capture a record URL (`/user/<id>`…); acting as user B, replay it → must be denied. This proves ownership is enforced at the database (row-level security), not just hidden in the UI.
  - **Input validation:** a malformed or oversized payload is rejected by server-side schema validation before it reaches business logic.
  - **Parameterized queries:** all SQL uses parameterized statements / prepared statements — no query built by string-concatenating user input. This is the actual SQL-injection defense; input validation alone is not it. Grep the changed code for string-built SQL.
  - **Secrets:** no credentials or keys hardcoded; injected at runtime from the environment; none present in the built artifact or its logs.
  - **Rate limiting:** active on public endpoints.
  - **Error hygiene:** unhandled errors return a generic message — no stack trace, query, or internal path leaks to the client.
  - **CORS:** restricted to the expected origin(s), not `*`, on credentialed endpoints.

  **Non-web profiles.** The rows above are written for a web app. If the artifact is another shape, name the matching profile once instead of justifying rows one by one — the rows a profile keeps are still checked with real evidence:
  - **CLI tool:** auth, cookies, IDOR, rate limiting, CORS → N/A. Still checked: input validation (untrusted args, files, env), secrets (none in the binary, repo, or logs), error hygiene (no secret-leaking traces), parameterized queries if it touches a database.
  - **Library / package:** endpoint rows → N/A. Still checked: input validation at the public API boundary, no secrets in the published artifact, error hygiene, and no unexpected new dependencies in the lockfile.
  - **Data pipeline / job:** cookies, CORS → N/A. Still checked: secrets, parameterized queries, input validation on ingested data — plus the operational-readiness gate below in full (idempotency on retry stands in for rate limiting).

  A failure here blocks the deploy. Route it back like any other finding: an enforcement bug → fix in code; a missing rule in the matrix → back to Phase 3.
- **Pass the operational-readiness gate before deploying.** The security gate proves it is safe; this proves it survives load. Check against the Phase 3 expected-scale target:
  - **Indexes:** every hot-path query has a supporting index. Confirm with the query planner (e.g. `EXPLAIN`) on a hot query, not by assumption — an unindexed query that is fast on demo data is a full scan in production.
  - **Statelessness:** no per-user/session state in process memory. State lives in the database or a shared store, so a second replica or a restart loses nothing. Verify the app still works correctly after a restart mid-session, or with more than one instance running.
  - **Monitoring + alerting:** logs flow to somewhere queryable, and an alert fires on critical failures (error spike, downtime). You must be able to answer "what is broken?" without a user telling you. Confirm an alert path actually exists — not just that logging is on.
  - **Rate limiting / backpressure:** confirmed active (cross-references the security gate) so one client cannot exhaust the service.

  A failure here blocks the deploy. A schema/index/statelessness gap routes back to Phase 3 — it is a design fix, not a deploy tweak.
- **Green checks prove only what they exercise.** Automated checks that don't build and boot the *actual deployable artifact* say nothing about whether it ships — they can pass while the shipped build is broken. Name what your checks do **not** cover (the real artifact, the real entrypoint, the real runtime) and close that gap by hand before deploying.
- **Automated checks are advisory unless the host enforces them as a required gate — know which yours is.** If merges aren't blocked on red or pending checks, a human must confirm every check is green (not pending, not skipped) before merging. Reading a green dashboard or an un-blocked merge control is not the same as confirming the checks actually passed.
- **Superpowers `finishing-a-development-branch`** presents a fixed menu whose first option (normal repo) is *"Merge back to <base-branch> locally"*. Allowed here: the push-and-PR option or the keep option (normal menu: "Push and create a Pull Request" / "Keep the branch as-is"; detached HEAD: "Push as new branch and create a Pull Request" / "Keep as-is") — never a merge option. Pick by meaning, not number — the detached-HEAD menu numbers and words them differently. Both executors invoke this skill straight after their final review; hold it until Phases 8 and 9 are approved. The merge itself comes last, per the ordering below.
- **Never push straight to the default branch.** Every change — regardless of how small it looks — lands through a pull request, so CI runs before the code merges. A "trivial" direct push is exactly the case that skips the gate that would have caught it.
- **Re-validate the deploy procedure against current code — don't trust a stale note.** A deploy command that worked before can break when imports/dependencies/structure change. Ask explicitly: *"does this build include everything the app imports?"* before running it.
- **Irreversible/outward actions go LAST, after verification.** Do not merge to the main branch, write to production data, or deploy until the riskiest unknown is proven. Correct order: verify artifact → deploy → confirm health → then merge/seed/announce. Never sequence a merge or a prod data write ahead of "does it even boot?"
- **Watch the new deployment's health before declaring success.** A "deploy complete" message is not a healthy service. Confirm health + routes + (where possible) a real end-to-end call before telling anyone it's ready.
- **A rollback is only real if its target still exists — verify before you rely on it.** "We can just roll back" is an assumption, not a safety net: hosts prune or expire previous builds, so a deploy you called reversible may have nothing to return to. Confirm the rollback target exists before treating a deploy as low-risk. If it's gone, stop trying to resurrect it — recover by fixing the source and rebuilding forward, which is the real recovery vehicle anyway (a deployment rollback does not undo already-merged history).

**Exit gate:** Artifact verified locally; security gate and operational-readiness gate passed with real evidence; deployed; health + routes confirmed live; rollback path known. Only then is the work "done."

---

## Execution Discipline (applies across all phases)

- **Honor the active skill's checklist — don't override process steps for "speed."** If a skill says create todos / track tasks, do it. The scaffolding exists to keep both you and the user oriented; skipping it loses visibility and drops threads.
- **Open every file you cite before writing code or tests against it.** Never reference a fixture, helper, function, or path you have not actually read — assumed interfaces produce plans that fail on contact.
- **Verify before declaring readiness.** "Ready to test" / "done" / "should work" are claims; each needs evidence (a real run, a real response, a confirmed health check) before it leaves. The failures in this project clustered exactly where readiness was declared ahead of verification.

---

## Running on Superpowers (checked against v7.0.1)

[Superpowers](https://github.com/obra/superpowers) chains `brainstorming` → `writing-plans` → `subagent-driven-development` / `executing-plans` → `finishing-a-development-branch`, and each handoff skips at least one gate in this file. `using-superpowers` itself says user instructions (`CLAUDE.md`) outrank skills, so paste this list into your project's `CLAUDE.md` — it is the only part of this section that needs to be loaded every session:

```markdown
## Workflow overrides for Superpowers
Where a Superpowers skill and this list disagree, this list wins.
- Name the tier and get my confirmation before any change — including "quick, clear tasks", "just dive in", bug fixes (systematic-debugging) and spikes. Every tier works on a branch, never the starting branch; spikes never merge.
- Specs/plans: [gitignored — always pass them by absolute path | committed — move them into the worktree at Phase 6 and commit there]. Never commit them to the starting branch.
- Design doc = Phase 3 spec: include the Phase 3 sections and run the Phase 3 checkpoint before asking me to approve it.
- After writing-plans: no execution-method question until the end of Phase 6. Plan approval is not a go; execution starts only when I say "start Phase 7".
- Plan Global Constraints copy the access-control matrix, scale target, reuse list, config rule and ownership map verbatim.
- Worktrees: always isolate, no need to ask (native tool, else `.worktrees/`), at the start of Phase 6. If `.worktrees` isn't gitignored or creation fails, stop and ask; never work in place. On resume, enter the existing worktree.
- Phase 6 RED stubs: after proving RED, move them into their owning tasks; never commit failing tests ahead of their task.
- During execution also stop and ask when: a previously passing test fails; a ruling would change the access matrix, schema, a public interface or scale design; a task needs a file outside the plan.
- Before the executor deletes its workspace, copy the ledger's Ruling / parked / minor (deferred) / "no reachable spec" lines into the plan under `## Execution record`.
- finishing-a-development-branch: not before Phases 8–9 are approved; then only the push-and-PR or keep option, never a merge option.
```

**After a Superpowers upgrade**, re-check these before trusting the notes in this file: where `brainstorming` saves the design doc and what its hard gate hands off to; `writing-plans`' plan header and execution handoff; the executors' stop conditions, what an implementer receives (`scripts/task-brief`), and whether the workspace is still deleted at finish; the `finishing-a-development-branch` menu; and the release notes for anything on adversarial review ([#1803](https://github.com/obra/superpowers/issues/1803)) or plan shape ([#2587](https://github.com/obra/superpowers/issues/2587)).

---

## Quick Reference

```
Tier check       Full pipeline (default) | Quick (small bounded change): branch → blast radius → change+test → real-run verify; deploy gates never skipped · bug fix / spike also tier-checked
Prerequisites    Load CLAUDE.md, ROADMAP.md (optional), relevant code — confirm with user

Phase 1          Context Priming       Confirm project understanding — user approves before Phase 2 (Superpowers: brainstorming's first message is this summary)
Phase 2          Exploration           Mandatory: superpowers brainstorming · Ask only — define why + constraints + what's different
                 EXIT GATE             All 3 questions answered clearly before Phase 3 — stated before brainstorming's approaches message
Phase 3          Spec Writing          Behavior, interfaces, edge cases, assumptions + access-control matrix + expected scale + reuse + config boundaries
                 CHECKPOINT            Spec vs. codebase: conflicts + unverified assumptions fixed — BEFORE design-doc approval
                 OUTPUT                YYYY-MM-DD-[feature]-spec.md (+ optional spec-[feature].html only if asked)
Phase 4          Plan Writing          Ordered steps with exit states and verification + Global Constraints (matrix/scale/reuse/config verbatim + Ownership map)
                 HANDOFF               writing-plans asks "which execution method?" → not yet, after Phase 6
                 CHECKPOINT            5 adversarial questions answered with specific findings
                 OUTPUT                YYYY-MM-DD-[feature]-plan.md (+ optional plan-[feature].html only if asked)
Phase 5          Adversarial Review    Break the plan + command dry-run + design-shape pass + abuse-case (security) + scale + reinvention/hardcode · fresh subagent when risky
                 LOOP-BACK             Surface fix → Ph.4 | Arch issue → Ph.3 | Wrong problem → Ph.2
Phase 6          TDD Planning          Worktree first (resume = enter existing) · test matrix written INTO plan tasks · RED stubs proven, then moved into owning tasks · pick method · explicit "start Phase 7"
Phase 7          TDD Implementation    In the Phase 6 worktree · Red→Green→Refactor, vertical slices · extra stops (regression, design ruling, out-of-map file) · structural review after core tasks · save Execution record
Phase 8          Post-Implementation   Plan vs. reality (every ruling = divergence), doc updates flagged
Phase 9          Living Doc Update     After each phase + on checkpoint triggers (gate cleared, context warning, user signal)
Phase 10         Deployment & Release  Prove artifact locally → pass security + operational-readiness gates → deploy → confirm health → then merge/seed/announce · PR only, never direct push to default branch · finishing-a-development-branch: "Push + PR" / "Keep" only, after P8–9
Cross-phase      Execution Discipline  Honor skill checklists · open files before citing · verify before claiming ready
```

---

## Core Rule

> Generation mode finds answers. Review mode finds problems.
> Every checkpoint and exit gate in this workflow forces a mode switch at the right moment.
> Do not treat them as optional. They exist to catch the failures that look invisible until implementation.
