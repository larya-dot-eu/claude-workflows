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

1. Keep `Claude-Workflows-Best-Practices-Compact.md` loaded (drop it in your project, or load it as a skill / paste it at
   the start of a session). Have `Claude-Workflows-Best-Practices.md` available for the agent to open per
   phase.
2. Tell the agent to follow it for the feature at hand.
3. Hold the gates: a phase isn't approved until *you* write the confirmation. Don't let it skip ahead.

## License

MIT.
