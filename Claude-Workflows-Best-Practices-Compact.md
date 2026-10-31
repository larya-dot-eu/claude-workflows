# Claude Workflows — Compact

Always-on spine. Superpowers handoff map + `CLAUDE.md` override block: **`Superpowers-Adapter.md`**. Full detail/rationale/output-formats: **`Claude-Workflows-Best-Practices.md`** — read matching section when enter phase or need full checklist. This file enough to hold discipline; full doc enough to execute. **Sync rule:** both files = one spec; any phase/gate/checklist change lands in both in same commit.

**Prime rule:** Work phases in order. Phase clears only when *user* writes approval ("approved", "looks good", "proceed") — never self-clear gate. Generation phases produce; review phases (Phase 3/4 checkpoints, Phase 5, Phase 10 gates) exist to *break* work, not defend.

**Tier check (before anything):** Full pipeline = default for feature-shaped work. **Quick** (typo, config tweak, doc edit, obvious one-file fix — user confirms tier): skip P1–6 → branch first (Quick has no P6 worktree) → state blast radius (open every touched file + grep callers) → change + test → real-run verify. P8–10 still apply if it ships; deploy gates never skipped. Brainstorming "just dive in" / "quick, clear task" ≠ tier — still name + confirm. Bug fix (`systematic-debugging`) / spike: tier check + branch **before** any instrumentation/test; re-check tier at root cause; spike never merges. Quick change grows past named blast radius / raises design question / crosses data boundary → stop, restart full. Unsure → full.

## Phases — do → exit gate

- **0 · Prereqs** — load `CLAUDE.md`, `ROADMAP.md` (optional — if absent, note + continue), touched code; summarize understanding → user confirms.
- **1 · Context Priming** — state architecture, constraints, conventions, prior decisions → user confirms picture. (Superpowers: brainstorming's first message = this summary; don't repeat it.)
- **2 · Exploration** — mandatory before creative work: superpowers `brainstorming`. Ask only, propose nothing · search existing code for prior solutions, list reuse candidates (none → say so, don't assume) Proposals only as marked guesses about *what*, never *how* → can answer: exact problem? constraints? what different? — state answers **before** brainstorming's approaches message.
- **3 · Spec** — behavior · interfaces · edge cases · **transactional integrity** (atomic vs eventual) · assumptions · **access-control matrix** · **expected scale** · **reuse** (name existing code built on) · **presentation vs logic** (colors/copy/thresholds/flags in CSS/config, never inline). If auth tokens/sessions: ask *"stolen credential revocable instantly?"* Superpowers design doc (short or full) = this spec: add these sections to it, run codebase checkpoint **before** asking approval (after approval brainstorming jumps to writing-plans). Spec/plan gitignored → absolute paths everywhere (worktree has no gitignored files); committed → on feature branch only → spec verified vs codebase, no unverified assumptions → user approves.
- **4 · Plan** — default skill: superpowers `writing-plans` (fallback: gstack `/plan`). Ordered steps, each with exit-state + how verified · **Global Constraints** copy matrix + scale + reuse + config rule verbatim (subagents see only task + constraints) · **Ownership map inside Global Constraints** (text before Task 1 reaches no implementer: one owner per fact, trait home, import direction, boundary error types, event→handler, state over time) → answer 5 checkpoint Qs with findings → user approves. writing-plans asks "execution method?" → not yet, after P6.
- **5 · Adversarial Review** — break plan (inline if ≤5 tasks + no data boundary; else 1 fresh-context subagent, most capable model). + **command dry-run** (run every test/build cmd plan names, real env) + **design-shape pass** (fact w/ 2 owners, optional field for always-present fact, split traits, branch on kind name, untyped boundary error, no import direction, event w/o handler) + **security abuse pass** (IDOR, RLS, authz, unvalidated input) + **scale pass** (what melts at peak ×10) + **reinvention/hardcode pass** (reuse existing code; values in config not inline). Loop back: surface → P4, architectural → P3, wrong problem → P2; >⅓ steps reworked → restart P3 → structurally sound → user approves.
- **6 · TDD Planning** — create isolated workspace **first** (superpowers `using-git-worktrees`, else feature branch; never let it commit `.gitignore` to starting branch or fall back to in-place; resume = enter existing worktree; committed spec/plan → move into worktree). Interfaces → Ownership map + task Interfaces; test matrix → test steps **inside owning tasks** (`task-brief` cuts heading-to-heading; trailing `## TDD` lands only on last task); top-3 RED tests proven in real suite, then (Superpowers) moved verbatim into owning tasks + stub files removed — red tests committed ahead of tasks stall baseline/`task-done` → agreed, no impl yet, execution method chosen, user says "start Phase 7" (plan approval ≠ go).
- **7 · TDD Impl** — in P6 workspace, never the session's starting branch. Vertical slices, Red→Green→Refactor, no scope creep; regression stops everything. Superpowers executors "rule, don't stall" → `CLAUDE.md` adds stops: regression · ruling touching matrix/schema/public interface/scale · file outside plan's map. Core abstractions first → structural review before dependents. Before executor deletes workspace: copy ledger `Ruling:` + `parked` + `minor (deferred)` + "no reachable spec" lines into plan `## Execution record` → all steps done, tests green, record saved.
- **8 · Post-Impl Review** — plan vs reality; flag doc updates · duplicated logic / inlined config value (only visible once written). Every Execution-record ruling = divergence → matches spec / spec updated / reverted. Zero rulings + no divergence → say so explicitly, don't leave it implied by silence → reported → user sign-off.
- **9 · Living Docs** — update work plan + `CLAUDE.md` (carry access-control matrix + scale target) + `ROADMAP.md`. Checkpoint on triggers (gate cleared · harness context warning/compaction · user says session long) so fresh session resumes from doc alone — don't wait for a context percentage.
- **10 · Deploy** — prove artifact boots locally → pass **security gate** → pass **ops gate** → deploy → confirm health → **then** merge/seed/announce. Irreversible/outward actions last. Land through a PR, never a direct push to default branch — no exception for "trivial." `finishing-a-development-branch`: only the push-and-PR or keep option (wording + numbering differ on detached HEAD), never a merge option; hold until P8–9 approved.

## Phase 10 — Security gate

Evidence from real requests, not "should be fine." Skip row only if genuinely N/A (no SQL, no auth cookies, no such boundary) — say which and why.

`auth → 401/403 when unauthenticated` · `session cookies HttpOnly + Secure + SameSite` · `IDOR: replay A's record URL as B → denied (ownership at DB / RLS)` · `server-side input validation` · `parameterized SQL — no string-built queries` · `no hardcoded secrets` · `rate limiting on public endpoints` · `generic errors — no stack trace leak` · `CORS not *`

Non-web artifact? Name profile once (CLI / library / pipeline — full doc lists which rows stay live) instead of row-by-row N/A. Kept rows still need real evidence.

## Phase 10 — Operational-readiness gate

Checked vs Phase 3 scale target:

`indexes on hot-path queries (verify EXPLAIN)` · `stateless — no in-memory session; survives restart / 2nd replica` · `monitoring + alerting live` · `rate limiting active`

## Every phase

- **Absence ≠ confirmation.** Empty grep, green suite that never hits changed path, silent log = *unverified*, not safe. Open actual source.
- **Evidence before "done."** "Should work" / "ready" = claim — back with real run, response, or health check.
- **Open every file before cite it.** No assumed interfaces, fixtures, signatures.
- **Design-level** security/scale failure routes back to **Phase 3** — not deploy-time patch.
