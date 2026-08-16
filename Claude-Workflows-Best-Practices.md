# Claude Planning - Implementation Workflows and Best Practices

> **Invoke this skill at the start of any new feature, integration, or implementation session.**
> **Approval is explicit.** A phase is not approved until the user writes a clear confirmation (e.g. "approved", "looks good", "proceed").
> Work through every phase in order. Do not skip phases. Do not proceed past an exit gate until it is explicitly cleared.
>
> **This is the full reference.** For everyday use, keep [`Claude-Workflows-Best-Practices-Compact.md`](./Claude-Workflows-Best-Practices-Compact.md) loaded as the always-on spine and read the matching section here when you enter a phase or need a full checklist — that keeps token cost and drift down on long sessions.
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
  Phases 8–10 still apply when the change ships: the deploy gates are never skipped — only the planning phases are.
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

**Exit gate (hard stop):** Before proceeding to Phase 3, you must be able to answer all three:
1. What is the exact problem being solved?
2. What are the constraints?
3. What makes this case different from existing patterns?

If you cannot answer all three clearly — stay in Phase 2 and ask the user for the missing clarity.

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

### Output Format

One required output, one optional companion — saved to your spec directory, e.g. `docs/specs/`, or `docs/superpowers/specs/` if you run the [superpowers](https://github.com/obra/superpowers) plugin (gitignored — local only, never committed; if `CLAUDE.md` names a different path, use that):

**1. Markdown spec (required — for Claude):**
`YYYY-MM-DD-[feature-name]-spec.md` — structured prose with headers covering behavior, interfaces, edge cases, transactional integrity, assumptions, the access-control matrix, and the expected-scale target. This is what future sessions read — and what Phase 4 builds the plan from: spec first, plan derived from it.

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

### Transition Checkpoint Before Phase 5

After writing the plan, run these five questions against it. Answer each one with specific findings — not "yes":

> 1. Is verification built in at each step, not just at the end?
> 2. Are tasks and steps grouped by what is independently vs. dependently testable?
> 3. Did you extract everything relevant from the codebase and the conversation — constraints, limitations, non-obvious edge cases?
> 4. Are there external dependencies — APIs, file paths, database states, service availability — that the plan assumes exist but does not verify first?
> 5. Which claims are most likely wrong — and did you verify each against the actual source? This includes an empty grep, a green suite that never exercises the changed path, a silent log, or anything the plan marked "most likely wrong" or "verify on contact".

Fix any issues found before proceeding.

**Exit gate:** All five questions answered with concrete findings. All issues resolved. User has approved the plan.

### Output Format

One required output, one optional companion — saved to your plans directory, e.g. `docs/plans/`, or `docs/superpowers/plans/` if you run the superpowers plugin (gitignored — local only, never committed; if `CLAUDE.md` names a different path, use that):

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

Check:
- Trace each step's intermediate state: after this step, is the codebase consistent or is it broken between steps?
- Draw the actual dependency graph: what must already exist before each step can run?
- What did you observe in the codebase that is not yet documented in the plan?
- **Absence is not confirmation.** An empty grep, a green suite that never exercises the changed path, a missing file, a silent log — each means "unverified," not "safe." If a search returns nothing, widen it (wrong file, wrong name, wrong dir) and open the actual source before concluding the thing is absent or fine. Never infer a signature or behavior from a sibling's usage when you can read the definition.
- **Re-attack the plan's own flagged risks first.** Any claim the plan marked "most likely wrong" or "verify on contact" gets opened and confirmed against source in *this* review — it is the first thing to break, not the thing deferred to execution.
- **Run an abuse-case pass against the access-control matrix.** The checks above attack correctness; now attack security. For each endpoint or data path the plan touches, ask how an attacker abuses it: Can one user reach another user's records by changing an ID (IDOR)? Is the ownership rule enforced at the database (row-level security), or only in app code that a crafted request skips? Can a protected route be hit unauthenticated, or an admin route reached by header/path tricks? Is any input trusted before server-side validation? Every "allowed" cell in the matrix needs a plan step that enforces it; every gap is a finding.
- **Run a scale pass against the expected-scale target.** Now attack load. Take the Phase 3 numbers and ask what melts at peak ×10: Does a hot-path query run without an index, or scan/join a large table? Will a table grow unbounded with no archival or pagination? Is any per-user/session state held in process memory, so it breaks the moment there's a second replica or a restart? Is the schema shaped for the demo (the convenient join) rather than the access pattern? Each one is a design finding to fix in the plan now — these do not patch cleanly after the schema and traffic are real.

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

Define before writing any implementation code:
- What interface changes are needed? (functions, methods, APIs, data shapes)
- Which behaviors must be tested first? (critical paths, complex logic, integration points)
- Can each component have a deep module design? (small interface, complex logic inside)
- Can each component be designed for testability? (inject dependencies, return results instead of side effects, no hidden state)

Output a prioritized list of behaviors to test with interface definitions agreed.

### Output Format

Do not create a new TDD document. Split the output by what each piece actually is:

- **Interface definitions + prioritized behavior list** — append a `## TDD` section to the existing Phase 4 plan file (`<plans-dir>/YYYY-MM-DD-[feature-name]-plan.md`): concrete signatures and the prioritized behavior list with rationale. Test priority is plan material; it lives with the plan.
- **Failing test stubs for the top 3 behaviors** — write these directly into the project's test suite (wherever this repo keeps tests — e.g. `tests/`, `core/tests/`, `backend/tests/`) as real failing (RED) tests. Do not transcribe stubs into a doc — a stub in markdown only has to be retyped as a real test in Phase 7. These stubs *are* the start of Phase 7's RED step.

**Exit gate:** Interface design agreed with the user. Test priority order defined (in the plan file). The top-3 failing test stubs written as real RED tests in the test suite. No implementation code written yet.

---

## Phase 7 — TDD Implementation

**Isolation:** before executing, ensure an isolated workspace exists — the **superpowers** `using-git-worktrees` skill (native tool, or git worktree fallback) if installed; otherwise a feature branch by hand. Do not implement directly on the branch you started the session on.

**Execution skill:** drive this phase with a plan-execution + TDD process. Public options that implement this discipline: the **superpowers** skills (`executing-plans` for review-checkpoint structure, `subagent-driven-development` for lean-context per-task subagents, `test-driven-development` for the Red→Green→Refactor loop), or **gstack** (`/spec`, `/ship`). The per-feature plan names which; with neither installed, run the Red→Green→Refactor loop below by hand.

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

**Exit gate:** All plan steps implemented. All tests passing. No unplanned changes introduced.

---

## Phase 8 — Post-Implementation Review

Check:
- Did the implementation match the plan? If not, document what changed and why.
- Did any new constraints or patterns surface that should be added to `CLAUDE.md`?
- Did any edge cases appear during implementation that were not in the spec?
- Does `ROADMAP.md` need updating if direction shifted?

If no divergence from the plan is found, state that explicitly ("no divergence found") rather than leaving it implied by silence — an unstated "no issues" and an unchecked item look identical in a log.

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

## Quick Reference

```
Tier check       Full pipeline (default) | Quick (small bounded change): blast radius → change+test → real-run verify; deploy gates never skipped
Prerequisites    Load CLAUDE.md, ROADMAP.md (optional), relevant code — confirm with user

Phase 1          Context Priming       Confirm project understanding — user approves before Phase 2
Phase 2          Exploration           Mandatory: superpowers brainstorming · Ask only — define why + constraints + what's different
                 EXIT GATE             All 3 questions answered clearly before Phase 3
Phase 3          Spec Writing          Behavior, interfaces, edge cases, assumptions + access-control matrix + expected scale
                 CHECKPOINT            Spec vs. codebase: conflicts + unverified assumptions fixed
                 OUTPUT                YYYY-MM-DD-[feature]-spec.md (+ optional spec-[feature].html only if asked)
Phase 4          Plan Writing          Ordered steps with exit states and verification
                 CHECKPOINT            5 adversarial questions answered with specific findings
                 OUTPUT                YYYY-MM-DD-[feature]-plan.md (+ optional plan-[feature].html only if asked)
Phase 5          Adversarial Review    Break the plan + abuse-case pass (security) + scale pass (load)
                 LOOP-BACK             Surface fix → Ph.4 | Arch issue → Ph.3 | Wrong problem → Ph.2
Phase 6          TDD Planning          Interfaces + test priority agreed before any code written
Phase 7          TDD Implementation    Isolated workspace first (worktree/branch) · Red→Green→Refactor, vertical slices, scope creep rule enforced
Phase 8          Post-Implementation   Plan vs. reality, doc updates flagged
Phase 9          Living Doc Update     After each phase + on checkpoint triggers (gate cleared, context warning, user signal)
Phase 10         Deployment & Release  Prove artifact locally → pass security + operational-readiness gates → deploy → confirm health → then merge/seed/announce · PR only, never direct push to default branch
Cross-phase      Execution Discipline  Honor skill checklists · open files before citing · verify before claiming ready
```

---

## Core Rule

> Generation mode finds answers. Review mode finds problems.
> Every checkpoint and exit gate in this workflow forces a mode switch at the right moment.
> Do not treat them as optional. They exist to catch the failures that look invisible until implementation.
