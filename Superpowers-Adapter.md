# Superpowers Adapter — running this workflow on top of Superpowers

**Checked against:** [obra/superpowers](https://github.com/obra/superpowers) **v7.0.1** (2026-10-21).
Re-check this file whenever Superpowers releases. Its skill handoffs change between versions, and this
file exists *because* of those handoffs (see [Re-validating after a Superpowers upgrade](#re-validating-after-a-superpowers-upgrade)).

This file is the "skin" that goes between Superpowers and the 10-phase workflow in
[`Claude-Workflows-Best-Practices.md`](./Claude-Workflows-Best-Practices.md). Superpowers chains its skills on its own:
`brainstorming` → `writing-plans` → `subagent-driven-development` / `executing-plans` →
`finishing-a-development-branch`. Each skill hands off straight to the next one, and **each handoff
skips at least one of this workflow's gates**. This file names every one of those handoffs, says what
gets skipped, and gives the override.

**Why the override works:** `using-superpowers` says *"User instructions (CLAUDE.md, AGENTS.md, …,
direct requests) take precedence over skills."* So the overrides belong in your project's `CLAUDE.md`
(block below), not only in a file the agent may or may not have read. The compact spine carries a
short version so the overrides survive `/clear` and compaction.

---

## 1. Paste this into your project's `CLAUDE.md`

```markdown
## Workflow overrides for Superpowers (v7.x)

This project runs the 10-phase workflow in Claude-Workflows-Best-Practices.md on top of Superpowers.
Where a Superpowers skill and this section disagree, this section wins.

- **Tier first.** Opting out of brainstorming's questions does not opt out of the workflow. Name the
  tier (Full / Quick) and get my confirmation before any change, including "quick, clear tasks", bug
  fixes (systematic-debugging) and spikes. Every tier works on a branch, never the starting branch.
  A spike is throwaway and never merges.
- **Specs and plans:** design doc = Phase 3 spec, saved to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`;
  plans to `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`. Do not commit them to the branch you
  started on. [Pick one: "They are gitignored — always pass them to skills and subagents by absolute
  path." | "Commit them on the feature branch once it exists."]
- **Worktrees:** yes, always isolate (no need to ask) — native worktree tool if there is one, else
  `.worktrees/`. Create it at the start of Phase 6, before any test file is written. If `.worktrees`
  isn't gitignored, or creation fails, stop and ask — never commit `.gitignore` to the starting branch
  and never work in place. In a new session, if `git worktree list` shows this plan's worktree, enter
  it; never create a second one.
- **After brainstorming's design doc:** before you ask me to approve it, run the Phase 3 checkpoint
  (conflicts with existing code, unverified assumptions) and confirm it has the Phase 3 required
  sections. My approval of the doc clears Phase 3.
- **After writing-plans:** do not ask me to pick an execution method yet. Phase 4 checkpoint → Phase 5
  adversarial review → Phase 6 TDD planning come first. Ask about the execution method at the end of
  Phase 6. Approving a plan is not a go: execution starts only when I say "start Phase 7".
- **Global Constraints in every plan** must copy, verbatim, the spec's access-control matrix, the
  expected-scale target, the reuse list, the config-boundary rule, and the Ownership map. Implementer
  and reviewer subagents see their task brief plus Global Constraints, not the spec.
- **Phase 6 RED stubs:** after proving RED, move each stub's code into its owning task's failing-test
  step and remove the stub file. Never commit failing tests ahead of their task.
- **During execution** (subagent-driven-development or executing-plans), stop and ask me, in addition
  to the skill's own four stop conditions, when: a previously passing test fails; a ruling would change
  the access-control matrix, the schema, a public interface, or the scale design; or a task needs a
  file outside the plan's file map.
- **Before the executor deletes its workspace:** copy the ledger's `Ruling:`, `parked`,
  `minor (deferred)` and "no reachable spec" lines into the plan file under `## Execution record`.
  Phase 8 reviews every ruling as a divergence.
- **finishing-a-development-branch:** do not invoke it until Phases 8 and 9 are approved. Then offer
  the push-and-PR option or the keep option (normal menu: "Push and create a Pull Request" / "Keep the branch as-is"; detached HEAD: "Push as new branch and create a Pull Request" / "Keep as-is") — never a merge option.
  Phase 10 runs before the PR is merged.
```

Fill in the bracket in the second bullet with your choice (see [Break 3](#break-3--the-spec-and-plan-are-not-in-the-worktree)).

---

## 2. Phase ↔ skill map (v7.0.1)

| Workflow phase | Superpowers skill | Gate the skill skips on its own | Override |
|---|---|---|---|
| Tier check | `using-superpowers`, `brainstorming` "quick, clear task: do it" | Tier confirmation, blast radius | Break 1 |
| (side routes) | `systematic-debugging` ("Fix this bug"), brainstorming spikes | Tier check, isolation, plan, review | Break 13 |
| Prereqs + Phase 1 | `brainstorming` → *Look Before You Ask* + *Your First Message* | Explicit Phase 1 confirmation | Break 2 |
| Phase 2 | `brainstorming` → *The Conversation*, *Play It Back* | "Ask only, propose nothing" until exit gate | Break 2 |
| Phase 3 | `brainstorming` → *Lay out the approaches*, *The Written Design*, builder check | Phase 3 required sections + codebase checkpoint; where the doc is committed | Breaks 3, 4 |
| Phase 4 | `writing-plans` (+ Self-Review) | 5 checkpoint questions; goes straight to "pick an execution method" | Breaks 5, 6 |
| Phase 5 | *(none — removed after v5.0, see [#1803](https://github.com/obra/superpowers/issues/1803))* | Whole phase | Break 6, 7 |
| Phase 6 | *(none — TDD steps are written into each plan task)* | Separate TDD planning; RED stubs on starting branch / stalling the executor | Breaks 8, 10 |
| Phase 7 | `using-git-worktrees` + `subagent-driven-development` or `executing-plans` + `test-driven-development` | Regression stop, scope-creep stop | Breaks 9, 10 |
| Phase 8 | SDD/executing-plans final whole-branch review | Plan-vs-reality reconciliation; ledger deleted | Break 11 |
| Phase 9 | *(none)* | — | Run by hand |
| Phase 10 | `finishing-a-development-branch`, `verification-before-completion` | PR-only; merge after deploy | Break 12 |

---

## 3. Breaks found, and the fix for each

Each entry says **what breaks**, **where** (the skill text that causes it), **how** it is fixed, and
**when** the fix applies. They came from reading the v7.0.1 skill sources end to end, from issue
[#1803](https://github.com/obra/superpowers/issues/1803) (adversarial review) and from issue
[#2587](https://github.com/obra/superpowers/issues/2587) (plans fix the type model task by task).

### Break 1 — Opting out of questions skips the tier check

- **What:** `brainstorming` says a request where "everything that matters is in the request" is a
  quick, clear task: *"Do it, and say what you did."* If the user didn't ask for brainstorming, it also
  offers *"if you'd rather I just dive in, say so"*, and then *"this skill is done"*. Both skip this
  workflow's tier confirmation and blast-radius step. That fits a cornflower-blue icon. It does not fit
  a "small" change to an auth check.
- **Where:** `brainstorming/SKILL.md` → *First: What Do You Actually Know?*, *Your First Message*.
- **How:** Saying "just dive in" opts out of *questions*, not out of the workflow. The agent still
  names the tier and gets confirmation. A quick change still states its blast radius.
- **When:** First message of every request.

### Break 2 — Brainstorming merges Prereqs, Phase 1, Phase 2 and the start of Phase 3

- **What:** v7 brainstorming reads the project before its first message, plays the request back,
  then asks questions. It also proposes ("A proposal they can correct … often beats a question"),
  lays out 2–3 approaches, and sizes the work. The workflow's Phase 2 says *ask only, propose nothing*.
  If you run both literally, you either do Phase 1 twice (token cost, which is the maintainer's main
  objection in #1803) or you skip the Phase 2 exit gate, because brainstorming moves to approaches
  as soon as *it* feels it understands.
- **Where:** `brainstorming/SKILL.md` → *Look Before You Ask*, *Your First Message*, *Lay out the approaches*.
- **How:** Map them, don't run both.
  - Brainstorming's first message **is** the Prereqs/Phase 1 summary. It must also name the
    `CLAUDE.md` constraints and prior decisions that apply. Your correction or confirmation of it
    clears Phase 1.
  - The questions and playback chunks **are** Phase 2. Proposals are fine as long as they are marked
    *as guesses about what you want*, never *how to build it*.
  - **Before** the *Lay out the approaches* message, the agent states the three Phase 2 exit answers
    (exact problem, constraints, what's different) plus the prior-solution search result. Approaches
    are the first Phase 3 act.
- **When:** Every Full-tier session.

### Break 3 — The spec and plan are not in the worktree

- **What:** The workflow says specs/plans are gitignored (local only). Superpowers says the design doc
  is *committed*. Both together break in two ways:
  1. **Committed:** brainstorming commits the design doc on *whatever branch you are on*, often the
     default branch. The worktree doesn't exist yet (it is created at execution). That is a direct
     commit to the default branch, which Phase 10 forbids.
  2. **Gitignored:** `using-git-worktrees` creates a fresh checkout under `.worktrees/`. Gitignored
     files **do not exist there**. The plan header's `**Spec:**` path is relative. The executor runs
     in the worktree, can't find the spec, and per the skill *"a plan with no reachable spec gets a
     ledger note — rulings made without one are provisional"*. Every ruling then argues from the plan
     alone. That is exactly the "invents stuff / forgets stuff" failure.
- **Where:** `brainstorming/SKILL.md` → *Where it goes*; `writing-plans/SKILL.md` → plan header `**Spec:**`;
  `executing-plans` / `subagent-driven-development` → *Setup*.
- **How:** Pick one, and state it in `CLAUDE.md` (brainstorming: "Your human partner's preferences
  override both"):
  - **Keep them local:** keep `docs/` gitignored, and write the `**Spec:**` line and every skill or
    subagent hand-off as an **absolute path** into the main checkout. `sdd-workspace` handles a plan
    outside the repo root (it records an absolute marker). Caveat: the main checkout's working tree is
    one copy, so two features in flight must use different file names (the date + topic prefix does that).
  - **Commit them:** at the start of Phase 6, move spec + plan from the main checkout into the new
    worktree, commit them on the **feature branch**, and delete the main-checkout copies (otherwise two
    copies drift, and Phase 8's "spec updated" lands in whichever one the agent opened). They are then
    reviewable in the PR.
  Either way, nothing is committed to the starting branch.
- **When:** Phase 3 save, Phase 4 save, Phase 7 start.

### Break 4 — The design doc has no slot for security, scale, reuse or config

- **What:** *The Written Design* covers intent, goals/non-goals/anti-goals, constraints, approaches,
  decided "how", what's left to the builder. It has no access-control matrix, no expected-scale target,
  no transactional-integrity call, no reuse list, no presentation-vs-logic rule. The builder-check
  subagent only asks what *it* would need to plan, so it won't ask who may read whose records. After
  approval the HARD-GATE says *"invoke superpowers:writing-plans and no other skill"*, so the Phase 3
  checkpoint (conflicts with existing code, unverified assumptions) never runs.
- **Where:** `brainstorming/SKILL.md` → *The Written Design*, *Builder check*, `<HARD-GATE>`.
- **How:** The design doc is the Phase 3 spec, so it must carry the Phase 3 required sections. Run the
  Phase 3 checkpoint **before** asking for approval, not after. The approval then really is the Phase 3
  gate, and the hand-off to `writing-plans` is correct. This applies to the **short** design doc for a
  small change too (one line per section, or "N/A — why"); the builder check runs only for projects, so
  for small changes nothing else will ask. For projects, add the Phase 3 sections to the builder check's
  domain line, e.g. *"a software engineer who must also implement the access rules and scale target"*.
- **When:** End of Phase 3.

### Break 5 — Security and scale rules never reach the subagents that write the code

- **What:** In subagent-driven development the controller reads the spec, but an implementer sees its
  task brief (cut from the plan by `task-brief`), the Global Constraints, and whatever interfaces and
  rulings the controller chooses to add. The reviewer sees the brief, the report, the diff and Global
  Constraints. Neither reads the spec. A spec rule that isn't in Global Constraints or the task text
  reaches the code only if the controller happens to remember it — and the cheap implementer model
  doesn't know the access matrix exists.
- **Where:** `writing-plans/SKILL.md` → *Global Constraints*; `subagent-driven-development/SKILL.md` →
  *Dispatch the implementer*, *Review the task*.
- **How:** Phase 4 copies the access-control matrix, scale target, reuse list and config-boundary rule
  **verbatim** into the plan's Global Constraints. Each abuse case found in Phase 5 becomes a test in
  the task that owns the code, not just a line in *Review Focus* (that section is capped at five).
- **When:** Phase 4 write, Phase 5 fixes.

### Break 6 — `writing-plans` jumps straight to execution

- **What:** After its own self-review, `writing-plans` asks *"Which execution approach would you
  prefer?"*. The executor then runs without pausing (*"Continuous execution"*). Phases 4-checkpoint, 5
  and 6 have nowhere to go. The skill's self-review is confirmatory (*"No need to re-review — just
  fix and move on"*). That is the gap issue #1803 describes: wrong test command (`npm run test --
  --run` → `vitest run --run`), un-activated venv, fragile regex, silently drifting field map. All
  four passed the self-review and would have failed on first contact.
- **Where:** `writing-plans/SKILL.md` → *Self-Review*, *Execution Handoff*.
- **How:** Answer the handoff with "not yet". Run the Phase 4 checkpoint, Phase 5 and Phase 6, and
  pick the execution method at the end of Phase 6. Watch the preset case: if you already named a method,
  `writing-plans` only asks you to review the plan and then *"use the preserved method"* — so your Phase 4
  "approved" starts execution and Phases 5–6 never happen. Hence the `CLAUDE.md` rule: plan approval is
  not a go; only "start Phase 7" is.
- **When:** End of Phase 4.

### Break 7 — Plans fix the design task by task (issue #2587)

- **What:** Each task has its own *Interfaces* block. Nothing in the plan says which type owns each
  domain fact. When two tasks need the same fact, each defines it. Pre-flight checks *consistency*
  (does Task 4 consume what Task 2 produces?), not *shape*. Per-task reviewers see one diff. The first
  review that sees the whole design is the final one, after later tasks have copied the mistakes. In
  #2587 that cost 8.5 h of fixes against 7 h of tasks. The measured fix: a design-shape check on the
  plan text found 7 blocking problems before any code existed. A type-model section alone did not
  reduce findings; the leftover findings were about runtime flow.
- **Where:** `writing-plans/SKILL.md` → *Task Structure* (Interfaces), *Self-Review* #3;
  `subagent-driven-development/references/preflight.md`.
- **How:**
  - Phase 4: the plan gets a short **Ownership map**, placed **inside Global Constraints** (text before
    Task 1 reaches no implementer — see Break 8). One owner per domain fact, one home per kind's traits,
    module import direction, the error type at each boundary, and **runtime flow**: which component
    handles each event and where state lives over time. Tasks cite its rows.
  - Phase 5: add a **design-shape pass**, run on the plan text: one owner per fact; no optional field
    for a fact its kind always has; no trait split across modules; no code branching on a kind's name;
    a typed error at each boundary; an import direction for every new module; every event has one
    handler.
  - Phase 7: if the plan has core-abstraction tasks that later tasks build on, run **one structural
    whole-branch review right after them**, before the dependents start (#2587's untried "skeleton
    first" option, at the cost of one extra review).
- **When:** Phases 4, 5, 7.

### Break 8 — Phase 6 output lands where nobody reads it, or where it stalls execution

- **What:** Three separate problems.
  1. Phase 6 writes the top-3 RED tests "into the real test suite". The worktree used to be created
     only in Phase 7, so the tests landed on the starting branch.
  2. `task-brief` cuts each implementer's brief from its `Task N` heading to the next `Task` heading.
     Text **before** Task 1 reaches no implementer. Text **after** the last task (an appended `## TDD`
     section) is glued onto the *last* task's brief only. The test matrix ends up in the wrong place.
  3. If the RED stubs are committed ahead of their tasks, the suite is red before Task 1. The worktree
     skill's baseline check stops on failing tests; `executing-plans`' `task-done` refuses to record any
     task whose test run fails; SDD implementers run the full suite before committing and chase failures
     they don't own; and the per-task review diff (`BASE..HEAD`) no longer contains the test that drives
     the task.
- **Where:** `subagent-driven-development/scripts/task-brief`; `executing-plans/scripts/task-done`;
  `using-git-worktrees` → *Step 3: Verify Clean Baseline*; `implementer-prompt.md`.
- **How:** Create the worktree at the **start** of Phase 6. Write the test matrix **into each owning
  task** (its test steps, tagged `[Happy]/[Sad]/[Edge]`); interfaces go into the Ownership map (in Global
  Constraints) and the tasks' Interfaces blocks. Prove the three RED stubs in the real runner (that is the
  Phase 6 gate), then copy each stub's code verbatim into its owning task's failing-test step and
  **remove the stub file**. Each stub becomes its own task's RED → GREEN, inside that task's diff.
- **When:** Phase 6.

### Break 9 — "Rulings, not stalls" overrides the regression and scope-creep stops

- **What:** Both executors say *"Do not pause to check in"* and *"Conflicts, ambiguities, plan
  defects — decide them … and keep going."* They stop only for: irreversible/destructive action,
  security-sensitive action, an outside side effect (merge, push, publish), or a plan broken beyond
  guessing. The workflow's **regression rule** (a previously passing test fails → stop, ask) and
  **scope-creep rule** (don't extend the plan unilaterally) are not on that list. Left alone, the
  executor quietly rules its way past both and records it in a ledger you may never see (Break 11).
- **Where:** `subagent-driven-development/SKILL.md` and `executing-plans/SKILL.md` → *Rulings, not stalls*.
- **How:** Add stop conditions in `CLAUDE.md` (user instructions beat skills): regression; a ruling
  that changes the access matrix, schema, a public interface or the scale design; a file outside the
  plan's file map. Everything else stays a ledgered ruling. That keeps the speed the skill is built for.
  Also: `executing-plans` loads `test-driven-development`; `subagent-driven-development` does **not** — its
  implementers do TDD only "if task says to". Keep explicit failing-test steps in every task.
- **When:** Phase 7.

### Break 10 — Isolation has three ways back onto the starting branch

- **What:** `using-git-worktrees`:
  1. asks for consent unless a preference is declared, and on "no" *"works in place"*;
  2. if `.worktrees/` isn't gitignored, *"Add to .gitignore, commit the change"* — on the current branch,
     i.e. often a direct commit to the default branch;
  3. if `git worktree add` is blocked (sandbox), *"you're working in the current directory instead"*.
  It also prefers the harness's native worktree tool over `.worktrees/`. And a session resumed after
  `/clear` or a Phase 9 hand-off starts in the main checkout, where Step 0 sees a normal repo and — with
  "always" declared — happily creates a *second* worktree from the default branch, without Phase 6's work.
- **Where:** `using-git-worktrees/SKILL.md` → *Step 0*, *Step 1a*, *Safety Verification*, *Sandbox fallback*.
- **How:** In `CLAUDE.md`: always isolate (native tool, else `.worktrees/`); if the ignore rule is
  missing or creation fails, stop and ask; on resume, enter the existing worktree from `git worktree
  list`. Add `.worktrees/` and `.superpowers/` to `.gitignore` once, through a normal PR, during setup.
  A plain clone (e.g. a cloud session) is not isolation — it still needs a feature branch.
- **When:** Setup; start of Phase 6; every resumed session.

### Break 11 — The executor deletes the evidence Phase 8 needs

- **What:** When the final review is clean, both executors **delete the plan's workspace**, which
  holds the ledger with every `Ruling:` and deferred minor. The executor does list them all in its final
  chat message ("Rulings I made", "Deferred minors") — but chat is not durable: compaction, `/clear` or the
  Phase 9 hand-off to a fresh session loses it, and it is never written into the plan. Phase 8 then
  compares plan vs reality without the list of every place reality was decided by the agent, and can
  honestly-but-wrongly write "no divergence found".
- **Where:** `executing-plans/SKILL.md` → *Finish*; `subagent-driven-development/references/final-review.md` → *Finish*.
- **How:** Before deletion, copy the `Ruling:`, `parked`, `minor (deferred)` and "no reachable spec"
  lines into the plan file under `## Execution record` (commit it if plans are committed). In Phase 8,
  **every ruling is a divergence** and gets one of: *matches spec* / *spec updated* / *reverted*. "No
  divergence found" is only allowed when the record has zero rulings.
- **When:** End of Phase 7, Phase 8.

### Break 12 — `finishing-a-development-branch` offers "Merge locally" first

- **What:** Option 1 of its fixed menu (normal repo) merges into the base branch locally. The workflow
  says every change lands through a PR, and merging comes **after** deploy + health check. Both executors
  invoke it as their last step, so it runs before Phases 8–10. On a detached HEAD the menu is
  renumbered (1 = push + PR, 2 = keep), so "options 2/3 only" would ban the PR there.
- **Where:** `finishing-a-development-branch/SKILL.md` → *Step 4*.
- **How:** Hold it until Phases 8 and 9 are approved. Allowed: the push-and-PR option or the keep option (normal menu: "Push and create a Pull Request" / "Keep the branch as-is"; detached HEAD: "Push as new branch and create a Pull Request" / "Keep as-is") — never a merge option. Phase 10's deploy gates run against the PR's branch. Merge is
  the last step.
- **When:** End of Phase 7 → Phase 10.

### Break 13 — Bug fixes and spikes take side routes past every gate

- **What:** `using-superpowers` sends "Fix this bug" to `systematic-debugging` first: no brainstorming,
  no tier check, no worktree. Brainstorming's spikes *"skip the plan, implementation, and review
  process"* and are built wherever the session is. The Quick tier, meanwhile, skips Phase 6 — which is
  now where isolation happens — so a Quick change had no isolation step at all.
- **Where:** `using-superpowers/SKILL.md` → *Skill Priority*; `brainstorming/SKILL.md` → *Spike to feel
  things out*, `<HARD-GATE>`.
- **How:** Bug fix → tier check, then a branch, **before** `systematic-debugging` adds any
  instrumentation or test. Stop between its root-cause phase and its fix phase to re-check the tier: a
  root cause outside the stated blast radius escalates to Full. Spike → a throwaway branch, never merged; keeping it is a new Full-tier request.
  Quick tier → branch first, then blast radius.
- **When:** Any request that doesn't start with brainstorming.

---

## 4. What Superpowers already covers (don't duplicate it)

Your files repeat these. They are kept, but here is the Superpowers mechanism behind each, so you know
what to check rather than re-specify:

| Workflow rule | Superpowers v7.0.1 mechanism |
|---|---|
| Evidence before "done" | `verification-before-completion` (Iron Law, gate function) |
| Red → Green → Refactor | `test-driven-development`, loaded by `executing-plans` before Task 1 (SDD implementers only follow the task's own steps) |
| Phase 4 "exit state per step", #2309 task-state | Step granularity + *Interfaces Consumes/Produces* + pre-flight scan |
| Phase 4 Q3 "extract everything" | *Global Constraints* + *Review Focus* + Self-Review #1 spec coverage |
| Phase 8 "plan vs reality" (partly) | Final whole-branch review on the most capable model |
| Session checkpoint (Phase 9) for execution | Ledger at `.superpowers/sdd/<plan>/progress.md` survives compaction |
| HTML visual companion | Brainstorming's visual companion (browser tab) — offered when seeing helps |

## 5. Cost control (the #1803 objection)

The maintainer removed multi-pass review gates after v5.0 because of token cost. The adversarial pass
here is scaled, not removed:

- **Quick tier:** no Phase 5.
- **Full tier, plan ≤ 5 tasks, no data boundary:** Phase 5 runs inline in the session, plus the command
  dry-run (below). It is cheap and catches #1803's class of bug.
- **Full tier, larger or touching auth / schema / money:** Phase 5 runs as **one fresh-context subagent**
  on the most capable model, given the spec + plan paths and the Phase 5 checklist. One review seat,
  not a per-task loop.
- **Command dry-run (always in Phase 5):** run every distinct test/build command the plan names once
  against the real repo (e.g. `pytest --collect-only`, `vitest run --passWithNoTests`). This is cheaper
  than reasoning about them and catches the wrong-flag / wrong-venv class directly.

## Re-validating after a Superpowers upgrade

When Superpowers releases a new version, check these spots in the new version before trusting this file:

1. `brainstorming/SKILL.md` — where the design doc goes; what the HARD-GATE hands off to.
2. `writing-plans/SKILL.md` — plan header fields; Execution Handoff text.
3. `subagent-driven-development/SKILL.md`, `executing-plans/SKILL.md` — stop conditions; what an
   implementer/reviewer receives; whether the workspace is still deleted at finish.
4. `subagent-driven-development/scripts/task-brief` — what part of the plan reaches an implementer.
5. `finishing-a-development-branch/SKILL.md` — the option menu.
6. `RELEASE-NOTES.md` — anything mentioning review gates, adversarial review (#1803) or plan shape (#2587).

Update the version line at the top, and the breaks that changed.
