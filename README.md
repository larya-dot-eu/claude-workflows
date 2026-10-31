# Claude Workflows — Best Practices

A single, battle-tested process file for using an AI coding agent (Claude Code, Cursor, etc.) on real
features without shipping self-inflicted outages or security holes.

**Version:** v2.0.0 — the workflow as an invisible Claude Code plugin (`/wf on`). Previous: [v1.2.0](https://github.com/larya-dot-eu/claude-workflows/releases/tag/v1.2.0) — see [Releases](https://github.com/larya-dot-eu/claude-workflows/releases) for changelog.

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

## Why reuse and simplicity are baked in too

The third recurring failure isn't a crash or a breach — it's the agent cheerfully rebuilding something
you already have, or hardcoding a color and a label into logic where a config value belonged. Both are
invisible until someone reads the diff. So reuse rides the same touchpoints as security and scale:
Phase 2 runs a **prior-solution search** (find what already exists before proposing new code), Phase 3
records what's **reused** and keeps tweakable values (colors, copy, thresholds, flags) in config not
inlined, Phase 5 runs a **reinvention-and-hardcoding pass**, and Phase 8 catches the duplication that
only shows up once the code is written. Kept deliberately off the quick tier — trivial changes stay
trivial.

## Requirements

**Required:** an AI coding agent that reads Markdown and follows instructions — [Claude Code](https://claude.com/product/claude-code) is the reference target (works in Cursor and similar too). The workflow itself is plain Markdown. On Claude Code, the optional `wf` plugin (below) loads it for you; it needs only `python3` and `git`.

**Optional stack (what the author runs).** None of these are required — the workflow is tool-agnostic and only cites a couple of them as examples. They each make a phase smoother:

| Tool | Adds | Used in |
|------|------|---------|
| [gstack](https://github.com/garrytan/gstack) | Planning, review, and ship/deploy skills (`/spec`, `/ship`, `/review`) | Phases 3–4, 7, 10 |
| [superpowers](https://github.com/obra/superpowers) | Default skill for exploration (`brainstorming`), planning (`writing-plans`), workspace isolation (`using-git-worktrees`), and TDD + plan-execution (`subagent-driven-development`, `executing-plans`, `test-driven-development`), integration (`finishing-a-development-branch`). Checked against **v7.0.1** — see *Running on Superpowers* in the full doc | Phases 1–4, 6–8, 10 |
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

## The `wf` plugin — the workflow as an invisible skin (recommended)

Instead of prompting *"read Claude-Workflows-Best-Practices.md and let's do phase 4"* every time, switch
the skin on once and just answer the gates. It works like [ponytail](https://github.com/DietrichGebert/ponytail):
off until you turn it on, a level you choose, a status line that shows where you are.

**Install — once per machine** (Linux; needs `python3` and `git`, nothing else):

```
/plugin marketplace add larya-dot-eu/claude-workflows
```
```
/plugin install wf@claude-workflows
```

(Send them as two separate prompts.) Update later with `claude plugin update wf@claude-workflows`.

**Use it**

| Command | What it does |
|---|---|
| `/wf on` · `/wf on strict` | Switch the skin on for this project + branch (default level, or the one you name) |
| `/wf pause` · `/wf resume` | Go silent but remember the phase · continue where you paused |
| `/wf off` | Fully off, phase forgotten |
| `/wf lite` · `/wf standard` · `/wf strict` | Change level (switches on if off) |
| `/wf default strict` | Default level for new projects on this machine |
| `/wf status` · `/wf 5` · `/wf new` | Where am I · jump to a phase (loop-backs) · start a new feature |
| `/wf statusline` | Prints the one line to add to `~/.claude/settings.json` to see `[WF P4 · standard]` |

**Levels**

| Level | What Claude gets | Context cost |
|---|---|---|
| `lite` | The "Every phase" rules only (absence ≠ confirmation, evidence before done). No phases. Merge guard asks. | ~150 tokens once |
| `standard` | Compact spine + automatic phases: each phase's section from the full doc only when you enter it. Superpowers-aware. Merge guard asks. | ~1.3k once + one section per phase |
| `strict` | Standard + Phase 5 always by a fresh subagent, Quick tier always confirmed, constraints injected into every subagent, merges blocked before Phase 10. | same + a few lines per subagent |

**How phases move — without you prompting them.** When Claude reaches an exit gate it ends its
message with `[[gate P3]]`. Reply *approved* / *looks good* / *proceed* and the skin moves exactly one
phase and hands Claude only that phase's rules. Anything with *but*, *change*, a question mark, etc. is
not an approval, and a turn that ends without the marker clears the pending gate — a side question
can never be mistaken for approval. If a marker is ever missed, `/wf 4` puts you back on track. Going *back* (e.g. Phase 5
sends the plan back to Phase 4) is always your call: Claude recommends it, you type `/wf 4`; a
marker for an earlier phase is treated as a recap and never erases your timeline.

**What you see in the terminal** (shown to you only — none of it is sent to Claude, so it costs no context):

```
WF ▸ brainstorming started → Phase 0 (Tier + Prereqs)
WF ▸ Gate P1 approved → Phase 2 (Explore)
WF ▸ Gate P3 reached · checklist 7/10 (70%) · missing: access-control matrix, expected scale · not in file: reuse
WF ▸ ⚠ writing-plans — spec (Phase 3) is not approved yet
```

- **Checklist %** — every gate has a checklist taken from the full doc. Claude lists each item on its own
  line (`- expected scale: §4 of the spec` or `- expected scale: N/A — pure function`). Only real answers
  count: *missing*, *TBD*, *left out*, *partially* don't. For the spec (P3) and plan (P4, P6) the hook also
  checks the file: an item Claude calls covered that isn't in the file shows as *not in file*. It measures
  **coverage, not quality** — reading the gate is still your job.
- **Timeline** — `/wf status` shows `P0 ✓ · P1 ✓ · P2 ⚠ skipped · P3 70% (gate)`. A phase left without an
  approved gate (Claude jumping ahead, a skill starting early) is marked *skipped*, so you can see whether
  brainstorming really went through Phases 1, 2 and 3.
- **Status line** — `[WF P3 70% · ✓✓⚠ · standard]` (current phase, its checklist %, earlier phases).
- **strict** — when a gate has missing items, Claude gets one extra turn to do them (or mark them N/A with a
  reason) and ends at the gate again. Once per gate; never while Claude is asking you a question.

**With Superpowers.** When the skin is on, the skills drive the phases: `brainstorming` starts a feature
at the tier check, `writing-plans` enters Phase 4 (and is told not to ask for an execution method yet),
`subagent-driven-development` / `executing-plans` enter Phase 7 — or warn and stop if Phases 5–6
haven't happened — and `finishing-a-development-branch` is held until Phases 8–9 are approved. Keep
the override block from the full doc's *Running on Superpowers* section in your `CLAUDE.md`:
Superpowers only guarantees that `CLAUDE.md` outranks its skills.

**Merge guard.** While the skin is on, `git merge`, `git commit` or `git pull <other branch>` on main/master,
`git push` to main/master and `gh pr merge` ask you first (`strict`: blocked until Phase 10). It follows
branch switches inside one command (`git checkout main && git merge feat`), so Superpowers'
*merge locally* option is caught too.

**Several machines.** The phase is remembered on the machine you're using, per repo and branch —
nothing is added to your project. On another machine, `/wf on` guesses the phase from your spec and
plan files and asks you to confirm (*"Looks like Phase 5 — correct?"*).

**Your own rules.** If the project root has its own copy of the two workflow files, the skin uses
those instead of the plugin's. Those files are sent to Claude as the workflow rules, so treat them like a `CLAUDE.md`: in a
repo you didn't write (a fresh clone, a contributor's branch), read them before you `/wf on`.

## Without the plugin (manual setup)

**Shortcut — let Claude set it up for you.** Open Claude Code in your project and paste:

> Fetch `Claude-Workflows-Best-Practices.md` and `Claude-Workflows-Best-Practices-Compact.md` from
> https://github.com/larya-dot-eu/claude-workflows into the project root, then add the two hooks from
> that repo's README to this project's `.claude/settings.json` (merge with existing settings; the hook
> paths already point at the project root). If this project uses Superpowers, also append the override
> block from the full doc's *Running on Superpowers* section to `CLAUDE.md` and ask me which spec/plan
> storage option to fill in. Don't change anything else.

Restart the session afterwards and approve the hooks when Claude Code asks.

Or do it by hand — nothing activates on its own; cloning this repo just gives you the files. Setup in
**your** project:

1. Copy both workflow files into your project root (committed, so teammates get them too — don't put
   them in a gitignored dir like `docs/`). On Superpowers, also paste the override block from the full doc's
   *Running on Superpowers* section into your `CLAUDE.md`, and add `.worktrees/` and `.superpowers/` to `.gitignore` (in a
   normal PR) so the skills never commit that themselves on your current branch.
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

## Optional: manual hooks (only without the plugin)

Using the `wf` plugin? Skip this section — and remove these hooks if you added them earlier, or the
spine loads twice (`/wf on` warns you). The workflow is instructions, and instructions can drift on long sessions. Two copy-paste
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

- **SessionStart** injects the compact spine (~1,300 tokens, once, then prompt-cached) — and re-fires after
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
