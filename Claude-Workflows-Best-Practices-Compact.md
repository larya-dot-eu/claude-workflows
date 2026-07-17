# Claude Workflows — Compact

Always-on spine. Full detail/rationale/output-formats: **`Claude-Workflows-Best-Practices.md`** — read matching section when enter phase or need full checklist. This file enough to hold discipline; full doc enough to execute. **Sync rule:** both files = one spec; any phase/gate/checklist change lands in both in same commit.

**Prime rule:** Work phases in order. Phase clears only when *user* writes approval ("approved", "looks good", "proceed") — never self-clear gate. Generation phases produce; review phases (Phase 3/4 checkpoints, Phase 5, Phase 10 gates) exist to *break* work, not defend.

**Tier check (before anything):** Full pipeline = default for feature-shaped work. **Quick** (typo, config tweak, doc edit, obvious one-file fix — user confirms tier): skip P1–6 → state blast radius (open every touched file + grep callers) → change + test → real-run verify. P8–10 still apply if it ships; deploy gates never skipped. Quick change grows past named blast radius / raises design question / crosses data boundary → stop, restart full. Unsure → full.

## Phases — do → exit gate

- **0 · Prereqs** — load `CLAUDE.md`, `ROADMAP.md` (optional — if absent, note + continue), touched code; summarize understanding → user confirms.
- **1 · Context Priming** — state architecture, constraints, conventions, prior decisions → user confirms picture.
- **2 · Exploration** — ask only, propose nothing → can answer: exact problem? constraints? what different?
- **3 · Spec** — behavior · interfaces · edge cases · **transactional integrity** (atomic vs eventual) · assumptions · **access-control matrix** · **expected scale**. If auth tokens/sessions: ask *"stolen credential revocable instantly?"* → spec verified vs codebase, no unverified assumptions → user approves.
- **4 · Plan** — ordered steps, each with exit-state + how verified → answer 5 checkpoint Qs with findings → user approves.
- **5 · Adversarial Review** — break plan. + **security abuse pass** (IDOR, RLS, authz, unvalidated input) + **scale pass** (what melts at peak ×10). Loop back: surface → P4, architectural → P3, wrong problem → P2; >⅓ steps reworked → restart P3 → structurally sound → user approves.
- **6 · TDD Planning** — interfaces + test priority; write top-3 RED tests into real suite → agreed, no impl yet.
- **7 · TDD Impl** — vertical slices, Red→Green→Refactor, no scope creep; regression stops everything → all steps done, tests green.
- **8 · Post-Impl Review** — plan vs reality; flag doc updates → reported → user sign-off.
- **9 · Living Docs** — update work plan + `CLAUDE.md` (carry access-control matrix + scale target) + `ROADMAP.md`. Checkpoint on triggers (gate cleared · harness context warning/compaction · user says session long) so fresh session resumes from doc alone — don't wait for a context percentage.
- **10 · Deploy** — prove artifact boots locally → pass **security gate** → pass **ops gate** → deploy → confirm health → **then** merge/seed/announce. Irreversible/outward actions last.

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
