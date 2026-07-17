# Claude Workflows — Best Practices

A single, battle-tested process file for using an AI coding agent (Claude Code, Cursor, etc.) on real
features without shipping self-inflicted outages or security holes.

**→ [`Claude-Workflows-Best-Practices.md`](./Claude-Workflows-Best-Practices.md)**

## What it is

A 10-phase, gated workflow that takes a feature from vague intent to a verified deploy. Each phase ends
in an **exit gate** the human must clear before the agent proceeds. The spine is deliberate
mode-switching: generation phases (spec, plan, implement) alternate with review phases whose only job is
to *break* the work — because the bugs that matter are invisible until someone goes looking.

```
Prereqs → 1 Context → 2 Explore → 3 Spec → 4 Plan → 5 Adversarial Review
        → 6 TDD Plan → 7 TDD Build → 8 Post-Impl → 9 Living Docs → 10 Deploy
```

Two principles carry most of the weight:

- **Absence is not confirmation.** An empty grep, a green suite that never runs the changed path, a
  silent log — each means *unverified*, not *safe*. Open the real source before concluding anything.
- **Evidence before "done."** "Should work" is a claim, not a result. Every readiness statement needs a
  real run, a real response, a real health check behind it.

## Why did I build this?

Because I'm an ideot – I have lots of ideas. Some are good and some are bad.

But no matter what I want to do, I have one big problem: *mistakes are costly*.

We have eyes to visualise, not to follow instructions or files. That part is now for AI.

So, rather than adding it at the end, I wanted to build verification in from the start.

## Why security is baked in

> *"Most security problems in AI-coded apps aren't bad code — they're the agent not having the context
> to know the expected behavior for your specific app."*

That's the reason Phase 3 forces an **access-control matrix** (who may read/write what, scoped by an
ownership key), Phase 5 runs an **abuse-case pass** against it, Phase 9 mirrors it into `CLAUDE.md` so
every future session inherits it, and Phase 10 won't deploy until a **pre-deploy security gate** passes
against the locally-booted artifact (auth, IDOR/row-level security, input validation, secrets, rate
limiting, error hygiene, CORS).

## Why scale is baked in too

The same failure shows up as "a thousand users hit it and everything's on fire" — unindexed queries, a
demo-shaped schema, user state in process memory, no monitoring. Those are design decisions, not deploy
tweaks, so scale rides the same three touchpoints as security: Phase 3 states an **expected-scale
target** (traffic, data volume, where state lives), Phase 5 runs a **scale pass** (what melts at peak
×10?), and Phase 10 holds an **operational-readiness gate** (indexes on hot queries, stateless app,
monitoring + alerting live) before the deploy goes out.

## Requirements

**Required:** an AI coding agent that reads Markdown and follows instructions — [Claude Code](https://claude.com/product/claude-code) is the reference target (works in Cursor and similar too). Nothing to install; the workflow is plain Markdown you load into context.

**Optional stack (what the author runs).** None of these are required — the workflow is tool-agnostic and only cites a couple of them as examples. They each make a phase smoother:

| Tool | Adds | Used in |
|------|------|---------|
| [gstack](https://github.com/garrytan/gstack) | Planning, review, and ship/deploy skills (`/spec`, `/ship`, `/review`) | Phases 3–4, 7, 10 |
| [superpowers](https://github.com/obra/superpowers) | TDD + plan-execution skills (`executing-plans`, `subagent-driven-development`, `test-driven-development`) | Phases 6–7 |
| [context7](https://github.com/upstash/context7) | Live, version-correct library docs via MCP — backs "open the source before you cite it" | Phases 1–7 |
| [ponytail](https://github.com/DietrichGebert/ponytail) | Laziest-solution-that-works discipline — fights over-engineering during implementation | Phase 7 |
| [caveman](https://github.com/JuliusBrussee/caveman) *(optional)* | Terse, token-light output; also the style of the compact spine file | Any phase |

Without them you run the workflow by hand — the gates and checklists are the same. The doc's example paths (`docs/specs/`, `docs/plans/`) and tool names assume nothing; swap in your own.

## Two files

- **[`Claude-Workflows-Best-Practices-Compact.md`](./Claude-Workflows-Best-Practices-Compact.md)** — the always-on spine: phase order,
  every exit gate, and both deploy-gate checklists in keyword form. Small enough to keep loaded all
  session without burning tokens or letting the agent drift.
- **[`Claude-Workflows-Best-Practices.md`](./Claude-Workflows-Best-Practices.md)** — the full reference:
  rationale, output formats, and the complete checklists. Read one section at a time, on demand, when you
  enter a phase.

The compact file is enough to hold the discipline; the full file is enough to execute it.

## How to use it

**Shortcut — let Claude set it up for you.** Open Claude Code in your project and paste:

> Fetch `Claude-Workflows-Best-Practices.md` and `Claude-Workflows-Best-Practices-Compact.md` from
> https://github.com/larya-dot-eu/claude-workflows into the project root, then add the two hooks from
> that repo's README to this project's `.claude/settings.json` (merge with existing settings; the hook
> paths already point at the project root). Don't change anything else.

Restart the session afterwards and approve the hooks when Claude Code asks.

Or do it by hand — nothing activates on its own; cloning this repo just gives you the files. Setup in
**your** project:

1. Copy both workflow files into your project root (committed, so teammates get them too — don't put
   them in a gitignored dir like `docs/`).
2. Load the compact file each session — either paste it / reference it manually, or set up the hooks
   below once and it loads automatically in every session of that project.
3. Tell the agent to follow the workflow for the feature at hand.
4. Hold the gates: a phase isn't approved until *you* write the confirmation. Don't let it skip ahead.

Small, bounded changes (a typo, a config tweak, an obvious one-file fix) don't need the full pipeline —
the workflow's **Task Tiers** section defines a quick tier that skips the planning phases but never the
deploy gates.

## Holding a gate — what to check before you write "approved"

The gates only work if you actually read what you're approving. A rubber-stamped "approved" turns the
whole workflow into ceremony. The minimum look per gate:

- **Phase 1 (context):** is the summary actually *your* project, or a plausible-sounding generic one?
- **Phase 3 (spec):** read the **assumptions** and the **access-control matrix** — those two sections are
  where wrong specs hide. Is the expected-scale target your real number, or a made-up one you never confirmed?
- **Phase 4 (plan):** read the answers to the five checkpoint questions. A bare "yes" without concrete
  findings means the question wasn't really run.
- **Phase 5 (adversarial review):** did it report concrete findings (file, step, broken state), or did it
  praise the plan? Zero findings on a non-trivial plan is a red flag, not a pass.
- **Phase 10 (deploy):** demand pasted evidence — the actual `401` response, the actual `Set-Cookie`
  header, the actual `EXPLAIN` output. "Verified ✓" without output is a claim, not a result.

## Optional: enforce the spine with hooks (no plugin needed)

The workflow is instructions, and instructions can drift on long sessions. Two copy-paste
[Claude Code hooks](https://docs.claude.com/en/docs/claude-code/hooks) harden it. Create
`.claude/settings.json` **in your own project** (not in a clone of this repo — hooks are per-project
config, and once set they fire in every session of that project; commit the file and your whole team
gets them). Adjust the `cat` path to wherever you put the compact file:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "cat \"$CLAUDE_PROJECT_DIR/Claude-Workflows-Best-Practices-Compact.md\""
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '[Workflow] phases in order; gate clears only on explicit user approval; absence != confirmation; evidence before done.'"
          }
        ]
      }
    ]
  }
}
```

- **SessionStart** injects the compact spine (~950 tokens, once, then prompt-cached) — and re-fires after
  `/clear` and after auto-compaction, which is exactly when injected context would otherwise be lost. The
  full workflow logic is always present without ever repeating it per prompt.
- **UserPromptSubmit** re-pins only the four drift-prone rules (~20 tokens per prompt): phase order, no
  self-cleared gates, absence ≠ confirmation, evidence before done. The content lives in the spine; this
  line just keeps the discipline pinned on long sessions.

Both are read-only and work with plain Claude Code — no plugin, nothing to install.

Two things to expect on first use:

- Claude Code doesn't silently run newly added project hooks — on the next session start it asks you to
  review and approve them (also whenever they change outside the `/hooks` menu). Approve once; after
  that they fire automatically.
- Hook output is injected into the **agent's** context, not displayed in your chat — you won't see it on
  screen. To verify it's firing, use `Ctrl+R` (transcript view), `/hooks` (lists registered hooks), or
  `claude --debug`.

## License

MIT.
