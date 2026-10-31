#!/usr/bin/env python3
"""wf — the Claude-Workflows "invisible skin" for Claude Code.

One script for every hook. Usage (from hooks/hooks.json):  python3 wf.py <HookEvent>
Reads the hook's JSON on stdin, prints hook JSON on stdout (or nothing). Never fails loudly:
any error means "do nothing", so a broken skin can never break a session.

State lives on this machine only: $CLAUDE_PLUGIN_DATA/state/<sha256(repo+branch)>.json
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LEVELS = ("lite", "standard", "strict")
DEFAULT_LEVEL = "standard"
LIMIT = 9500  # hook additionalContext is capped at 10,000 chars
DOC = "Claude-Workflows-Best-Practices.md"
SPINE = "Claude-Workflows-Best-Practices-Compact.md"
PHASE_NAMES = {0: "Tier + Prereqs", 1: "Context", 2: "Explore", 3: "Spec", 4: "Plan",
               5: "Adversarial Review", 6: "TDD Plan", 7: "TDD Build", 8: "Post-Impl Review",
               9: "Living Docs", 10: "Deploy"}

HELP = ("/wf commands: `/wf on [lite|standard|strict]`, `/wf off`, `/wf pause`, `/wf resume`, "
        "`/wf lite|standard|strict`, `/wf default <level>`, `/wf status`, `/wf <0-10>` (jump to a phase), "
        "`/wf new` (new feature, back to the tier check), `/wf statusline`.")


# ---------------------------------------------------------------- documents

def split_sections(text):
    """[(heading, text)] for every '## ' heading outside ``` fences. Text includes the heading."""
    out, fence, cur_head, cur = [], False, None, []
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            if cur_head is not None:
                out.append((cur_head, "".join(cur)))
            cur_head, cur = line.rstrip("\n"), [line]
        elif cur_head is not None:
            cur.append(line)
    if cur_head is not None:
        out.append((cur_head, "".join(cur)))
    return out


def phase_section(doc_text, n):
    """The full-doc text for phase n (0 = Task Tiers + Prerequisites)."""
    parts = []
    for head, body in split_sections(doc_text):
        if n == 0 and (head.startswith("## Task Tiers") or head.startswith("## Prerequisites")):
            parts.append(body)
        elif n > 0 and re.match(rf"## Phase {n}\b", head):
            parts.append(body)
    return "".join(parts).rstrip("-\n ") + "\n"


def doc_path(name, env, cwd):
    """A project's own copy wins over the plugin's (lets a project customise its rules)."""
    for base in (repo_root(cwd), env.get("CLAUDE_PROJECT_DIR"), env.get("CLAUDE_PLUGIN_ROOT")):
        if base and (Path(base) / name).is_file():
            return Path(base) / name
    return None


def read_doc(name, env, cwd):
    p = doc_path(name, env, cwd)
    return p.read_text(encoding="utf-8") if p else ""


def every_phase_rules(spine_text):
    m = re.search(r"^## Every phase\n(.*?)(?=^## |\Z)", spine_text, re.S | re.M)
    return ("## Every phase\n" + m.group(1)).strip() if m else ""


# ---------------------------------------------------------------- git + state

def _git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def repo_root(cwd):
    return _git(cwd, "rev-parse", "--show-toplevel") if cwd else None


def repo_identity(cwd):
    """(git common dir, branch) — so worktrees of one repo share nothing but their repo."""
    common = _git(cwd, "rev-parse", "--git-common-dir")  # may be relative to cwd (works on old git)
    if not common:
        return (str(Path(cwd).resolve()), "")
    branch = _git(cwd, "symbolic-ref", "--short", "-q", "HEAD")  # works before the first commit
    if not branch:
        branch = "detached:" + (_git(cwd, "rev-parse", "HEAD") or "")
    return (str((Path(cwd) / common).resolve()), branch)


def current_branch(cwd):
    return _git(cwd, "symbolic-ref", "--short", "-q", "HEAD") or ""


def data_dir(env):
    d = env.get("CLAUDE_PLUGIN_DATA") or os.path.join(
        env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "claude-workflows")
    return Path(d)


class Store:
    def __init__(self, env):
        self.env = env
        self.dir = data_dir(env) / "state"

    def path(self, cwd):
        common, branch = repo_identity(cwd)
        key = hashlib.sha256(f"{common}\0{branch}".encode()).hexdigest()[:32]
        return self.dir / f"{key}.json"

    def default_level(self):
        try:
            lvl = json.loads((data_dir(self.env) / "config.json").read_text()).get("default_level")
            return lvl if lvl in LEVELS else DEFAULT_LEVEL
        except Exception:
            return DEFAULT_LEVEL

    def set_default_level(self, level):
        p = data_dir(self.env) / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            cfg = json.loads(p.read_text())
        except Exception:
            cfg = {}
        cfg["default_level"] = level
        _atomic_write(p, cfg)

    def blank(self):
        return {"enabled": "off", "level": self.default_level(), "phase": None,
                "gate_pending": None, "injected": None, "timeline": {}}

    def load(self, cwd):
        s = self.blank()
        try:
            s.update(json.loads(self.path(cwd).read_text()))
        except Exception:
            pass
        return s

    def save(self, cwd, state):
        p = self.path(cwd)
        p.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(p, state)

    @contextlib.contextmanager
    def locked(self, cwd):
        """Hold the state's lock across a whole load → modify → save."""
        p = self.path(cwd)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(str(p) + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield


def _atomic_write(path, obj):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1) if not isinstance(obj, bytes) else f.buffer.write(obj)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------- output helpers

def output(event, text, show=None):
    """Hook JSON: `text` goes to Claude (additionalContext), `show` is a line only the user sees."""
    out = {}
    if text:
        out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": text}
    if show:
        out["systemMessage"] = "WF ▸ " + show
    return out or None


def describe(state):
    if state["enabled"] == "off":
        return "off"
    ph = state["phase"]
    where = "no phase yet" if ph is None else f"Phase {ph} ({PHASE_NAMES.get(ph, '?')})"
    return f"{state['enabled']}, level {state['level']}, {where}"


def show_status(state):
    line = describe(state).replace(", level ", " · ").replace(", ", " · ")
    tl = timeline_text(state) if state["enabled"] != "off" and state["phase"] is not None else ""
    return line + (f"\n   {tl}" if tl and (state.get("timeline") or {}) else "")


def skin_context(state, env, cwd, with_phase=True, budget=LIMIT):
    """What Claude needs while the skin is on: spine (or lite rules) + current phase section,
    kept under `budget` characters (a phase that doesn't fit is given as an exact line range to read)."""
    spine = read_doc(SPINE, env, cwd)
    if state["level"] == "lite":
        return "Claude-Workflows skin (lite): apply these rules in every step.\n\n" + every_phase_rules(spine)
    parts = ["Claude-Workflows skin is on (level %s). This project follows the phased workflow below; "
             "the user clears every exit gate. When you reach a phase's exit gate, end your message with "
             "the line `[[gate P<n>]]` (n = the phase number) and wait for the user. If you answer a question "
             "while still waiting at that gate, end that message with the same line again." % state["level"],
             spine]
    if state["level"] == "strict":
        parts.append("Strict level: run Phase 5 as one fresh-context subagent on the most capable model; "
                     "the Quick tier always needs the user's explicit confirmation.")
    head = "\n\n".join(p for p in parts if p)
    if with_phase and state["phase"] is not None:
        head += "\n\n" + phase_context(state["phase"], env, cwd, budget - len(head) - 2)
    return head


def phase_lines(doc_text, n):
    """1-based (first, last) line numbers of phase n's section in the doc."""
    section = phase_section(doc_text, n).rstrip("\n")
    start = doc_text.find(section)
    if not section or start < 0:
        return None
    first = doc_text.count("\n", 0, start) + 1
    return first, first + section.count("\n")


def phase_context(n, env, cwd, budget=LIMIT):
    doc = read_doc(DOC, env, cwd)
    lead = f"Current phase: {n} ({PHASE_NAMES.get(n, '?')}). "
    text = lead + "Full rules for this phase:\n\n" + phase_section(doc, n)
    if len(text) <= budget:
        return text
    lines = phase_lines(doc, n)
    where = f" lines {lines[0]}–{lines[1]}" if lines else ""
    return (lead + f"Its rules are too long to include here: read `{doc_path(DOC, env, cwd)}`{where} "
            "now with the Read tool (just that range), before continuing.")


def statusline_snippet(env):
    script = data_dir(env) / "statusline.py"
    return ('Add this to ~/.claude/settings.json (it shows `[WF P4 · standard]` while the skin is on):\n'
            '```json\n"statusLine": {"type": "command", "command": "python3 %s statusline"}\n```\n'
            'If you already have a status line (e.g. ponytail), keep it and append the wf output: '
            '`<your command>; python3 %s statusline`.' % (script, script))


# ---------------------------------------------------------------- /wf commands

CMD_RE = re.compile(r"^\s*/wf(?::wf)?(?:\s+(.*))?\s*$", re.I | re.S)


def parse_command(prompt):
    m = CMD_RE.match(prompt or "")
    if not m:
        return None
    args = (m.group(1) or "").lower().split()
    if not args:
        return ("status", [])
    if args[0].isdecimal() and args[0].isascii():
        return ("phase", [args[0]])
    return (args[0], args[1:])


def run_command(cmd, args, state, store, env, cwd):
    """Apply a /wf command. Returns (new_state or None, context text for Claude)."""
    tell = "Tell the user in one short line: "
    if cmd in LEVELS:
        cmd, args = "on", [cmd]
    if cmd == "on":
        if args and args[0] in LEVELS:
            state["level"] = args[0]
        state["enabled"] = "on"
        guess = ""
        if state["phase"] is None and state["level"] != "lite":
            n, why = guess_phase(cwd, state.get("completed_at") or 0)
            if n is not None:
                state.update(phase=n, injected=n)
                guess = (f"\n\nNo saved phase for this branch on this machine; {why}. Ask the user: "
                         f"\"Looks like Phase {n} ({PHASE_NAMES[n]}) — correct? (`/wf <n>` to change)\"")
        lead = f"{tell}workflow skin ON ({describe(state)})." + guess + old_hooks_warning(cwd) + "\n\n"
        return state, lead + skin_context(state, env, cwd, budget=LIMIT - len(lead))
    if cmd == "resume":
        if state["enabled"] == "off":
            return None, tell + "the skin is off — use `/wf on`."
        state["enabled"] = "on"
        lead = f"{tell}workflow skin resumed ({describe(state)}).\n\n"
        return state, lead + skin_context(state, env, cwd, budget=LIMIT - len(lead))
    if cmd == "pause":
        if state["enabled"] == "off":
            return None, tell + "the skin is already off."
        state["enabled"] = "paused"
        return state, (tell + "workflow skin PAUSED (phase kept; `/wf resume` continues). Until it is "
                       "resumed, ignore the workflow phases and gate markers.")
    if cmd == "off":
        state.update(enabled="off", phase=None, gate_pending=None, injected=None)
        return state, (tell + "workflow skin OFF. From now on ignore the workflow phases, gates and "
                       "gate markers injected earlier in this session.")
    if cmd == "default" and args and args[0] in LEVELS:
        store.set_default_level(args[0])
        return None, f"{tell}default level for new projects on this machine is now {args[0]}."
    if cmd == "status":
        tl = timeline_text(state) if state["phase"] is not None else ""
        return None, f"{tell}workflow skin {describe(state)}." + (f" Timeline: {tl}." if tl else "")
    if cmd == "statusline":
        return None, "Show the user this, verbatim:\n\n" + statusline_snippet(env)
    if cmd == "phase":
        n = int(args[0])
        if not 0 <= n <= 10:
            return None, tell + "phases are 0–10. " + HELP
        if state["enabled"] == "off":
            state["enabled"] = "on"
        move_to(state, n)
        state.update(gate_pending=None, injected=n)
        lead = f"{tell}moved to Phase {n} ({PHASE_NAMES[n]}).\n\n"
        return state, lead + skin_context(state, env, cwd, budget=LIMIT - len(lead))
    if cmd == "new":
        if state["enabled"] == "off":
            state["enabled"] = "on"
        new_feature(state)
        state.update(phase=0, injected=0)
        lead = f"{tell}new feature — starting at the tier check.\n\n"
        return state, lead + skin_context(state, env, cwd, budget=LIMIT - len(lead))
    return None, "Show the user: unknown /wf command. " + HELP



# ---------------------------------------------------------------- phase engine

GATE_RE = re.compile(r"^\s*\[\[gate P(\d{1,2})\]\]\s*$")
APPROVE_RE = re.compile(
    r"^(approved?|i approve|looks good|lgtm|proceed|go ahead|ok(ay)?|yes|yep|ship it|"
    r"sounds good|perfect)\b", re.I)
HARMLESS_NO = re.compile(r"\bno (changes?|issues?|problems?|objections?|further (changes?|comments?))\b"
                         r"( needed)?", re.I)
VETO_RE = re.compile(r"\b(but|except|however|change|fix|instead|not|no|don'?t|wait|first|before|"
                     r"why|how|what|explain|redo|rename|remove|add)\b|\?", re.I)


def gate_from_message(msg):
    """Phase n if the message's last non-empty line, outside code fences, is `[[gate Pn]]`."""
    if not msg:
        return None
    fence, last = False, None
    for line in msg.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            last = None
            continue
        if line.strip():
            last = None if fence else line
    m = GATE_RE.match(last or "")
    n = int(m.group(1)) if m else None
    return n if n is not None and 0 <= n <= 10 else None


def is_approval(text):
    t = (text or "").strip()
    if not t or len(t) > 80 or t.startswith("/"):
        return False
    return bool(APPROVE_RE.match(t)) and not VETO_RE.search(HARMLESS_NO.sub("", t))


def move_to(state, n):
    """Set the phase and keep the timeline honest: phases left without an approved gate are
    'skipped'; going back (a loop-back) forgets everything from the target phase on."""
    old, tl = state["phase"], state.setdefault("timeline", {})
    if old is not None and n is not None:
        if n > old:
            for k in range(old, n):
                entry = tl.get(str(k), {})
                if entry.get("status") != "done":
                    tl[str(k)] = dict(entry, status="skipped")
        elif n < old:
            for k in [k for k in tl if int(k) >= n]:
                del tl[k]
    state["phase"] = n


def new_feature(state):
    state.update(phase=None, gate_pending=None, injected=None, timeline={})


def timeline_marks(state):
    """'✓✓⚠' for the phases before the current one ('' when nothing is recorded)."""
    tl, ph = state.get("timeline") or {}, state["phase"]
    if not tl or ph is None:
        return ""
    sym = {"done": "✓", "skipped": "⚠"}
    return "".join(sym.get(tl.get(str(k), {}).get("status"), "·") for k in range(0, ph))


def score_pct(entry):
    return round(100 * entry["found"] / entry["total"]) if entry.get("total") else None


def timeline_text(state):
    tl, ph = state.get("timeline") or {}, state["phase"]
    parts = []
    for k in range(0, 11):
        e = tl.get(str(k), {})
        pct = score_pct(e)
        if k == ph:
            parts.append(f"P{k} " + (f"{pct}% (gate)" if pct is not None and state.get("gate_pending") == k
                                     else "now"))
        elif e.get("status") == "done":
            parts.append(f"P{k} ✓" + (f" {pct}%" if pct is not None and pct < 100 else ""))
        elif e.get("status") == "skipped":
            parts.append(f"P{k} ⚠ skipped")
    return " · ".join(parts)


def enter_phase(state, n, env, cwd, lead):
    """Move to phase n; include that phase's section unless it was the last one injected."""
    move_to(state, n)
    state["gate_pending"] = None
    text = lead
    if state.get("injected") != n:
        text += "\n\n" + phase_context(n, env, cwd)
        state["injected"] = n
    return text


def engine_on(state):
    return state["enabled"] == "on" and state["level"] != "lite"


def on_stop(payload, env, store, cwd):
    state = store.load(cwd)
    if not engine_on(state):
        return None
    gate = gate_from_message(payload.get("last_assistant_message"))
    if gate != state.get("gate_pending") or (gate is not None and state["phase"] != gate):
        if gate is not None and state["phase"] != gate:
            move_to(state, gate)
        state["gate_pending"] = gate
        store.save(cwd, state)
    if gate is None:
        return None
    return output("Stop", None, f"Gate P{gate} reached · waiting for your approval")


def approve(state, env, cwd):
    gate = state["gate_pending"]
    tl = state.setdefault("timeline", {})
    tl[str(gate)] = dict(tl.get(str(gate), {}), status="done")
    if gate >= 10:
        state.update(phase=None, gate_pending=None, injected=None, completed_at=time.time())
        return ("The user approved the Phase 10 gate. The workflow is complete for this feature. "
                "Tell the user in one line; a new feature starts with brainstorming or `/wf new`.")
    nxt = gate + 1
    return enter_phase(state, nxt, env, cwd,
                       f"The user approved the Phase {gate} gate. Continue with Phase {nxt} "
                       f"({PHASE_NAMES[nxt]}) now, following its rules below.")


# skill name (after "plugin:") -> handler(state, env, cwd) -> text or None
def _skill_brainstorming(state, env, cwd):
    if state["phase"] is not None and state["phase"] <= 3:
        return None
    new_feature(state)
    return enter_phase(state, 0, env, cwd,
                       "New feature (brainstorming started). Brainstorming covers Phases 0–3: confirm the "
                       "tier first; its first message is the Phase 1 summary; state the Phase 2 exit answers "
                       "before its approaches message; its design doc is the Phase 3 spec. End each phase's "
                       "gate message with `[[gate P<n>]]`.")


def _skill_writing_plans(state, env, cwd):
    ph = state["phase"]
    if ph is None or ph < 3:
        return ("writing-plans was started, but the spec (Phase 3) is not approved yet. Stop and tell the "
                "user; finish the spec and get its approval first.")
    note = ("When writing-plans asks for an execution method: do not ask yet — Phase 4 checkpoint, "
            "Phase 5 and Phase 6 come first; the method is chosen at the end of Phase 6.")
    if ph in (3, 4):
        return enter_phase(state, 4, env, cwd, "Entering Phase 4 (Plan). " + note)
    return note


def _skill_executor(state, env, cwd):
    ph = state["phase"]
    if ph is None or ph < 6:
        return ("Plan execution was started, but Phase 5 (adversarial review) and Phase 6 (TDD planning) "
                "are not done for this feature. Stop and ask the user before executing.")
    note = ("Extra stop conditions: a previously passing test fails; a ruling would change the access "
            "matrix, schema, a public interface or the scale design; a task needs a file outside the plan. "
            "Before the workspace is deleted, copy the ledger's Ruling / parked / minor (deferred) lines into "
            "the plan under `## Execution record`.")
    if ph in (6, 7):
        return enter_phase(state, 7, env, cwd, "Entering Phase 7 (TDD Build). " + note)
    return note


def _skill_finishing(state, env, cwd):
    ph = state["phase"]
    if ph is not None and ph >= 10:
        return "Only the push-and-create-PR or keep option is allowed; never a merge option."
    return ("Hold finishing-a-development-branch: Phases 8 (post-implementation review) and 9 (living docs) "
            "come first and need the user's approval. After that, only the push-and-create-PR or keep "
            "option is allowed; never a merge option.")


def _skill_debugging(state, env, cwd):
    return ("Bug fix: name the tier and get the user's confirmation, and move to a branch, before adding "
            "any instrumentation or test. Re-check the tier once the root cause is found.")


SKILLS = {
    "brainstorming": _skill_brainstorming,
    "writing-plans": _skill_writing_plans,
    "subagent-driven-development": _skill_executor,
    "executing-plans": _skill_executor,
    "finishing-a-development-branch": _skill_finishing,
    "systematic-debugging": _skill_debugging,
}


def on_skill(name, event, env, store, cwd):
    fn = SKILLS.get((name or "").split(":")[-1])
    if not fn:
        return None
    state = store.load(cwd)
    if not engine_on(state):
        return None
    before = state["phase"]
    text = fn(state, env, cwd)
    store.save(cwd, state)
    short = (name or "").split(":")[-1]
    after = state["phase"]
    if after != before:
        show = f"{short} started → Phase {after} ({PHASE_NAMES[after]})"
    else:
        warn = text and ("Stop" in text or "not approved" in text or "Hold" in text)
        show = ("⚠ " if warn else "") + f"{short} — " + SKILL_SHOW[short][0 if warn else 1]
    return output(event, text, show)


# what the user sees when a skill doesn't change the phase: (warning, reminder)
SKILL_SHOW = {
    "brainstorming": ("", "already in this feature's Phases 0–3"),
    "writing-plans": ("spec (Phase 3) is not approved yet", "execution-method question waits until Phase 6"),
    "subagent-driven-development": ("Phases 5–6 are not done yet", "extra stop conditions + Execution record on"),
    "executing-plans": ("Phases 5–6 are not done yet", "extra stop conditions + Execution record on"),
    "finishing-a-development-branch": ("hold until Phases 8–9 are approved", "only push + PR or keep; no merge"),
    "systematic-debugging": ("", "tier check + branch before any debugging edits"),
}


def on_pre_tool(payload, env, store, cwd):
    if payload.get("tool_name") == "Bash":
        return on_bash(payload, env, store, cwd)
    if payload.get("tool_name") == "Skill":
        return on_skill((payload.get("tool_input") or {}).get("skill"), "PreToolUse", env, store, cwd)
    return None


def on_expansion(payload, env, store, cwd):
    return on_skill(payload.get("command_name"), "UserPromptExpansion", env, store, cwd)




def guess_phase(cwd, since=0):
    """Best guess of the phase from spec/plan files changed after `since` (a finished feature's
    files don't count): (phase, evidence) or (None, '')."""
    root = Path(repo_root(cwd) or cwd)
    def files(*dirs):
        return [p for d in dirs for p in sorted((root / d).glob("*.md"))
                if p.is_file() and p.stat().st_mtime > since]
    plans, specs = files("docs/superpowers/plans", "docs/plans"), files("docs/superpowers/specs", "docs/specs")
    for p in plans:
        if "## Execution record" in p.read_text(errors="ignore"):
            return 8, f"plan {p.relative_to(root)} has an Execution record"
    if plans:
        return 5, f"plan {plans[-1].relative_to(root)} exists"
    if specs:
        return 4, f"spec {specs[-1].relative_to(root)} exists"
    return None, ""



# ---------------------------------------------------------------- guards

DEFAULT_BRANCHES = ("main", "master")
_DEF = r"(?:main|master)"


_GIT = r"\bgit(?:\s+-(?:C|c)\s+\S+)*\s+"


def _hits_default(ref, branch):
    ref = ref.lstrip("+").split(":")[-1].removeprefix("refs/heads/")
    if ref in ("HEAD", "@"):
        ref = branch
    return ref in DEFAULT_BRANCHES


def guard_reason(command, branch):
    """Why this shell command would integrate into the default branch, or '' if it wouldn't."""
    c = command or ""
    on_default = branch in DEFAULT_BRANCHES
    if re.search(r"\bgh\s+pr\s+merge\b", c):
        return "`gh pr merge` merges a pull request"
    if on_default and re.search(_GIT + r"merge(?![-\w])", c):
        return f"`git merge` while on `{branch}` merges into the default branch"
    for m in re.finditer(_GIT + r"pull\b([^;&|\n]*)", c):
        refs = [a for a in m.group(1).split() if not a.startswith("-")][1:]
        if on_default and refs and not all(_hits_default(r, branch) for r in refs):
            return f"`git pull` of another branch while on `{branch}` merges it into the default branch"
    for m in re.finditer(_GIT + r"push\b([^;&|\n]*)", c):
        words = m.group(1).split()
        if "--all" in words or "--mirror" in words:
            return "`git push --all/--mirror` pushes the default branch too"
        refs = [a for a in words if not a.startswith("-")][1:]  # after the remote
        if any(_hits_default(r, branch) for r in refs):
            return "`git push` to the default branch"
        if not refs and on_default:
            return f"`git push` while on `{branch}` pushes the default branch"
    return ""


def on_bash(payload, env, store, cwd):
    state = store.load(cwd)
    if state["enabled"] != "on":
        return None
    reason = guard_reason((payload.get("tool_input") or {}).get("command"), current_branch(cwd))
    if not reason:
        return None
    strict = state["level"] == "strict" and (state["phase"] is None or state["phase"] < 10)
    why = (f"Workflow merge guard: {reason}. Changes land through a PR, and merging is the last step of "
           f"Phase 10 (after deploy + health check).")
    if strict:
        why += " Strict level blocks this before Phase 10; the user can `/wf 10` or `/wf standard` to allow it."
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny" if strict else "ask",
                                   "permissionDecisionReason": why}}


SUBAGENT_RULES = ("Workflow rules for this subagent: follow the plan's Global Constraints exactly (access-control "
                  "matrix, scale target, reuse list, config rule, ownership map). Absence is not confirmation: an "
                  "empty grep or a suite that never runs the changed path means unverified. Open every file before "
                  "you cite it. Never claim done without a real run. If a previously passing test fails, stop and "
                  "report it instead of working around it.")


def on_subagent(payload, env, store, cwd):
    state = store.load(cwd)
    if state["enabled"] == "on" and state["level"] == "strict":
        return output("SubagentStart", SUBAGENT_RULES)
    return None


def old_hooks_warning(cwd):
    root = Path(repo_root(cwd) or cwd)
    for name in ("settings.json", "settings.local.json"):
        p = root / ".claude" / name
        try:
            if SPINE in p.read_text() or "[Workflow] phases in order" in p.read_text():
                return (f"\n\nAlso tell the user: `{p.relative_to(root)}` still has the old manual workflow hooks, "
                        "so the spine is loaded twice. Remove those two hooks; the wf plugin replaces them.")
        except Exception:
            pass
    return ""


# ---------------------------------------------------------------- hook handlers

def install_statusline(env):
    """Copy this script to the data dir: a path that survives plugin updates, for the status line."""
    try:
        dst = data_dir(env) / "statusline.py"
        src = Path(__file__).resolve()
        if src != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            if not dst.is_file() or dst.read_bytes() != data:
                _atomic_write(dst, data)
    except Exception:
        pass


def on_prompt(payload, env, store, cwd):
    state = store.load(cwd)
    parsed = parse_command(payload.get("prompt", ""))
    if parsed:
        new, text = run_command(*parsed, state, store, env, cwd)
        if new is not None:
            store.save(cwd, new)
        install_statusline(env)
        return output("UserPromptSubmit", text, show_status(new or store.load(cwd)))
    if engine_on(state) and is_approval(payload.get("prompt")):
        if state.get("gate_pending") is None:
            return output("UserPromptSubmit",
                          "wf: no gate is pending, so this did not move the phase. If the user is approving a "
                          "gate, restate which gate in one line and end your message with its `[[gate P<n>]]` "
                          "line, so their next approval moves the phase.",
                          "no gate pending — phase unchanged")
        gate = state["gate_pending"]
        text = approve(state, env, cwd)
        store.save(cwd, state)
        nxt = state["phase"]
        show = (f"Gate P{gate} approved → feature complete" if nxt is None
                else f"Gate P{gate} approved → Phase {nxt} ({PHASE_NAMES[nxt]})")
        return output("UserPromptSubmit", text, show)
    return None


def on_session_start(payload, env, store, cwd):
    install_statusline(env)
    state = store.load(cwd)
    if state["enabled"] != "on":
        return None
    return output("SessionStart", skin_context(state, env, cwd))


HANDLERS = {
    "UserPromptSubmit": on_prompt,
    "SessionStart": on_session_start,
    "Stop": on_stop,
    "PreToolUse": on_pre_tool,
    "UserPromptExpansion": on_expansion,
    "SubagentStart": on_subagent,
}


def handle(event, payload, env):
    cwd = payload.get("cwd") or env.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    fn = HANDLERS.get(event)
    if not fn:
        return None
    store = Store(env)
    with store.locked(cwd):
        return fn(payload, env, store, cwd)


def statusline(payload, env):
    cwd = (payload.get("workspace") or {}).get("current_dir") or payload.get("cwd") or os.getcwd()
    state = Store(env).load(cwd)
    if state["enabled"] == "off":
        return ""
    ph = "–" if state["phase"] is None else state["phase"]
    if state["enabled"] == "paused":
        return f"[WF ⏸ P{ph}]"
    entry = (state.get("timeline") or {}).get(str(state["phase"]), {})
    pct = score_pct(entry) if state.get("gate_pending") == state["phase"] else None
    head = f"P{ph}" + (f" {pct}%" if pct is not None else "")
    marks = timeline_marks(state)
    return "[WF " + " · ".join(x for x in (head, marks, state["level"]) if x) + "]"


def main(argv):
    event = argv[1] if len(argv) > 1 else ""
    env = dict(os.environ)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if event == "statusline":
            # The status line runs outside the plugin: our state dir is this script's own dir.
            env.setdefault("CLAUDE_PLUGIN_DATA", str(Path(__file__).resolve().parent))
            print(statusline(payload, env), end="")
            return
        out = handle(event, payload, env)
        if out:
            print(json.dumps(out))
    except Exception:
        pass  # never break the session


if __name__ == "__main__":
    main(sys.argv)
