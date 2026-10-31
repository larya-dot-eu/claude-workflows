# Claude Workflows — Compact

Always-on spine. Full detail/rationale/output-formats: **`Claude-Workflows-Best-Practices.md`** — read matching section when enter phase or need full checklist. This file enough to hold discipline; full doc enough to execute. **Sync rule:** both files = one spec; any phase/gate/checklist change lands in both in same commit.

**Prime rule:** Work phases in order. Phase clears only when *user* writes approval ("approved", "looks good", "proceed") — never self-clear gate. End every exit-gate message with one line per item of that phase's **Gate checklist** (last line of each phase in the full doc; `- <item>: <where covered>` or `- <item>: N/A — why`), then the line `[[gate P<n>]]` (n = phase) — the `wf` plugin scores the items and advances on it. Generation phases produce; review phases (Phase 3/4 checkpoints, Phase 5, Phase 10 gates) exist to *break* work, not defend.

**Tier check (before anything):** Full pipeline = default for feature-shaped work. **Quick** (typo, config tweak, doc edit, obvious one-file fix — user confirms tier): skip P1–6 → branch first → state blast radius (open every touched file + grep callers) → change + test → real-run verify. P8–10 still apply if it ships; deploy gates never skipped. Brainstorming "just dive in", bug fix, spike ≠ tier — still confirm + branch. Quick change grows past named blast radius / raises design question / crosses data boundary → stop, restart full. Unsure → full.

## Phases — do → exit gate

- **0 · Prereqs** — load `CLAUDE.md`, `ROADMAP.md` (optional — if absent, note + continue), touched code; summarize understanding → user confirms.
- **1 · Context Priming** — state architecture, constraints, conventions, prior decisions → user confirms picture.
- **2 · Exploration** — mandatory before creative work: superpowers `brainstorming`. Ask only, propose nothing · search existing code for prior solutions, list reuse candidates (none → say so, don't assume) → state answers to: exact problem? constraints? what different? — before brainstorming's approaches message.
- **3 · Spec** — behavior · interfaces · edge cases · **transactional integrity** (atomic vs eventual) · assumptions · **access-control matrix** · **expected scale** · **reuse** (name existing code built on) · **presentation vs logic** (colors/copy/thresholds/flags in CSS/config, never inline). If auth tokens/sessions: ask *"stolen credential revocable instantly?"* Superpowers design doc = this spec (add these sections); checkpoint **before** approval. Gitignored spec/plan → absolute paths (worktree lacks them) → spec verified vs codebase, no unverified assumptions → user approves.
- **4 · Plan** — default skill: superpowers `writing-plans` (fallback: gstack `/plan`). Ordered steps, each with exit-state + how verified · Global Constraints copy matrix/scale/reuse/config + ownership map verbatim (subagents never read spec) → writing-plans' "execution method?" waits for P6 → answer 5 checkpoint Qs with findings → user approves.
- **5 · Adversarial Review** — break plan (fresh subagent if risky). + **command dry-run** + **design-shape pass** (one owner per fact) + **security abuse pass** (IDOR, RLS, authz, unvalidated input) + **scale pass** (what melts at peak ×10) + **reinvention/hardcode pass** (reuse existing code; values in config not inline). Loop back: surface → P4, architectural → P3, wrong problem → P2; >⅓ steps reworked → restart P3 → structurally sound → user approves.
- **6 · TDD Planning** — interfaces + test priority; worktree **first**; test matrix inside owning tasks, not appended; top-3 RED proven, then moved into owning tasks → agreed, no impl yet; plan approval ≠ go; go = user approves P6 gate ("start Phase 7").
- **7 · TDD Impl** — in P6 workspace, never the starting branch. Vertical slices, Red→Green→Refactor, no scope creep; regression stops everything — also for Superpowers executors ("rulings, not stalls"), plus design-changing ruling / out-of-plan file. Copy ledger rulings into plan `## Execution record` before workspace deleted → all steps done, tests green.
- **8 · Post-Impl Review** — plan vs reality; flag doc updates · duplicated logic / inlined config value (only visible once written). Each recorded ruling = divergence. No divergence found → say so explicitly, don't leave it implied by silence → reported → user sign-off.
- **9 · Living Docs** — update work plan + `CLAUDE.md` (carry access-control matrix + scale target) + `ROADMAP.md`. Checkpoint on triggers (gate cleared · harness context warning/compaction · user says session long) so fresh session resumes from doc alone — don't wait for a context percentage.
- **10 · Deploy** — prove artifact boots locally → pass **security gate** → pass **ops gate** → deploy → confirm health → **then** merge/seed/announce. Irreversible/outward actions last. Land through a PR, never a direct push to default branch — no exception for "trivial." `finishing-a-development-branch`: PR or keep only, after P8–9.

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
