# CLAUDE.md File Audit

Audit and rewrite this project's CLAUDE.md. Do not add new content speculatively — only include what's verifiably true for this repo.

1. Discover what this project actually is before verifying anything. Do not assume any of the following exist — check for each and only verify against what's actually present:
   - Package/dependency manifests (package.json, requirements.txt, go.mod, etc.) — if none exist, this is not a code project; verify content/structure claims only.
   - Build/deploy config (vercel.json, railway.toml, Dockerfile, docker-compose.yml, astro.config, etc.) — read these to learn real build/deploy commands, don't take CLAUDE.md's word for them.
   - Service/infra dependencies (database or cache connection config, auth provider SDK imports e.g. Clerk, ORM/schema files pointing at a DB e.g. Supabase) — confirm each by finding where it's actually wired into code or config, not by CLAUDE.md mentioning it.
   - CI/CD (.github/workflows, other pipeline config) — verify test/lint commands here match what CLAUDE.md claims, since this is the source of truth for what's actually enforced.
   - Environment/secrets scaffolding (.env.example, settings files) — confirms which services are expected to be configured, without needing live credentials.
If CLAUDE.md references a service, tool, or command you cannot find any trace of in the repo (config, import, lockfile entry, workflow step), flag it explicitly as unverifiable — don't silently keep it and don't silently delete it either; surface it so I decide.
If this project has no package manifest, no build config, and no service integration (e.g. a docs-only or static markdown/HTML repo), say so explicitly and skip the infra-verification steps entirely — don't invent scaffolding to check against.

2. Flag anything stale, unused, contradictory, or unverifiable — list these separately before rewriting, don't just silently drop them.
3. Rewrite from scratch, not by patching. Target under 150 lines total.
4. Structure:
   - Commands (exact build/test/lint/run/deploy commands, verified by finding them in package.json/Makefile/CI, not guessed)
   - Architecture (2-5 lines: how the pieces fit, not a file tree dump)
   - Conventions actually enforced in this codebase (not generic best practices)
   - Known gotchas / things that have broken before, if evidence exists in git history or comments
5. Only include a rule if you can point to where it's checked or enforced (lint rule, test, hook). If nothing enforces it, mark it "unenforced" or drop it.
6. Write every rule as a positive instruction, not a prohibition.
7. Add this exact "Response Style" block at the end:

## Response Style
- Be concise and engineering-focused. Result first, no task restatement.
- No generic background or explanation unless explicitly asked.
- For code changes, report only: changed files, behavior change, validation run, remaining risks.
- If no validation was run, say so directly.
- If no risk found, write "no additional risk found."
- Do not ask "would you like me to also..." — either do the obviously-implied next step or stop. This does not apply to phases that require explicit user approval by design.

8. Show me the old file, the flagged issues, and the new file side by side. Do not overwrite anything until I approve.
