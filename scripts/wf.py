#!/usr/bin/env python3
"""wf — the Claude-Workflows "invisible skin" for Claude Code.

One script for every hook. Usage (from hooks/hooks.json):  python3 wf.py <HookEvent>
Reads the hook's JSON on stdin, prints hook JSON on stdout (or nothing). Never fails loudly:
any error means "do nothing", so a broken skin can never break a session.

State lives on this machine only: $CLAUDE_PLUGIN_DATA/state/<sha256(repo+branch)>.json
"""
import contextlib
import fcntl
import functools
import hashlib
import json
import os
import re
import shlex
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

HELP_SHOWN = ("The /wf help text was shown to the user directly in their terminal. Reply with one short "
              "line only, e.g. 'Help is shown above.' Do nothing else.")
HELP = ("/wf commands: `/wf on [lite|standard|strict]`, `/wf off`, `/wf pause`, `/wf resume`, "
        "`/wf lite|standard|strict`, `/wf default <level>`, `/wf status`, `/wf <0-10>` (jump to a phase), "
        "`/wf new` (new feature, back to the tier check), `/wf dirs <spec> <plan>`, `/wf statusline`.")


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


@functools.lru_cache(maxsize=16)
def repo_identity(cwd):
    """(git common dir, branch) — so worktrees of one repo share nothing but their repo.
    Cached for one hook run (handle() clears it): every hook needs it several times."""
    common = _git(cwd, "rev-parse", "--git-common-dir")  # may be relative to cwd (works on old git)
    if not common:
        return (str(Path(cwd).resolve()), "")
    branch = _git(cwd, "symbolic-ref", "--short", "-q", "HEAD")  # works before the first commit
    if not branch:
        branch = "detached:" + (_git(cwd, "rev-parse", "HEAD") or "")
    return (str((Path(cwd) / common).resolve()), branch)


def current_branch(cwd):
    branch = repo_identity(cwd)[1]
    return "" if branch.startswith("detached:") else branch


def data_dir(env):
    d = env.get("CLAUDE_PLUGIN_DATA") or os.path.join(
        env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "claude-workflows")
    return Path(d)


class Store:
    def __init__(self, env):
        self.env = env
        self.dir = data_dir(env) / "state"

    def path(self, cwd):
        """This repo+branch's own state file (may hold a redirect, see resolve)."""
        common, branch = repo_identity(cwd)
        key = hashlib.sha256(f"{common}\0{branch}".encode()).hexdigest()[:32]
        return self.dir / f"{key}.json"

    def pointer(self, cwd):
        """Per-repo note of the state file saved last — what a new branch follows."""
        common = repo_identity(cwd)[0]
        return self.dir / (hashlib.sha256(common.encode()).hexdigest()[:32] + ".last")

    def resolve(self, cwd):
        """The state file to use: a branch the skin moved away from redirects to where it went."""
        p = self.path(cwd)
        try:
            target = json.loads(p.read_text()).get("moved_to")
            if target and Path(target).is_file():
                return Path(target)
        except Exception:
            pass
        return p

    def follow(self, cwd):
        """The workflow switches branch (Phase 6 worktree, Quick tier, bug fixes). When this branch has
        no state yet and the repo's last active feature is on, carry it over and leave a redirect behind.
        Returns the branch it came from, or None."""
        mine = self.path(cwd)
        if mine.exists():
            return None
        try:
            ptr = json.loads(self.pointer(cwd).read_text())
            origin = Path(ptr["path"])
            state = json.loads(origin.read_text())
        except Exception:
            return None
        branch = repo_identity(cwd)[1]
        if state.get("moved_to") or state.get("enabled", "off") == "off" or ptr.get("branch") == branch:
            return None
        moved = dict(state, followed_from={"path": str(origin), "branch": ptr.get("branch"), "state": state})
        self.save_at(mine, moved, branch, cwd)
        _atomic_write(origin, {"moved_to": str(mine), "branch": ptr.get("branch")})
        return ptr.get("branch") or "?"

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

    def peek(self, cwd):
        """The saved state, read without locking, or None when this repo+branch has none."""
        try:
            return json.loads(self.resolve(cwd).read_text())
        except Exception:
            return None

    def load(self, cwd):
        s = self.blank()
        try:
            s.update(json.loads(self.resolve(cwd).read_text()))
        except Exception:
            pass
        return s

    def save(self, cwd, state):
        self.save_at(self.resolve(cwd), state, repo_identity(cwd)[1], cwd)

    def save_at(self, p, state, branch, cwd=None):
        p.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(p, state)
        if cwd:
            _atomic_write(self.pointer(cwd), {"path": str(p), "branch": branch})

    def unfollow(self, cwd, state):
        """/wf new on a followed branch: this branch becomes its own feature; the original goes back."""
        origin = state.pop("followed_from", None)
        if not origin:
            return
        with contextlib.suppress(Exception):
            _atomic_write(Path(origin["path"]), origin["state"])

    @contextlib.contextmanager
    def locked(self, cwd):
        """Hold the state's lock across a whole load → modify → save."""
        p = self.path(cwd)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.pointer(cwd)) + ".lock", "w") as lock:   # one lock per repo: follow/redirects span branches
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield


def _atomic_write(path, obj, indent=1):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=indent) if not isinstance(obj, bytes) else f.buffer.write(obj)
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
    if not spine:
        spine = (f"(Workflow rules file not found: `{SPINE}` is neither in this project nor in the plugin. "
                 "Tell the user once; the plugin may need reinstalling.)")
    if state["level"] == "lite":
        rules = every_phase_rules(spine) or spine
        return "Claude-Workflows skin (lite): apply these rules in every step.\n\n" + rules
    parts = ["Claude-Workflows skin is on (level %s). This project follows the phased workflow below; "
             "the user clears every exit gate. When you reach a phase's exit gate, end your message with "
             "the line `[[gate P<n>]]` (n = the phase number) and wait for the user. If you answer a question "
             "while still waiting at that gate, end that message with the same line again. Going back to an earlier "
             "phase (e.g. the Phase 5 loop-back table) is the user's call: recommend it and ask them to type "
             "`/wf <n>`." % state["level"],
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
    rule = "\n\n" + checklist_instruction(n, checks_from_doc(doc, n) or CHECKS.get(n, []))
    if not doc:
        return (lead + f"Its full rules are unavailable (rules file not found: `{DOC}` is neither in this project "
                "nor in the plugin); work from the checklist below and tell the user once." + rule)
    text = lead + "Full rules for this phase:\n\n" + phase_section(doc, n) + rule
    if len(text) <= budget:
        return text
    lines = phase_lines(doc, n)
    where = f" lines {lines[0]}–{lines[1]}" if lines else ""
    return (lead + f"Its rules are too long to include here: read `{doc_path(DOC, env, cwd)}`{where} "
            "now with the Read tool (just that range), before continuing." + rule)


def claude_dir(env):
    return Path(env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"))


def _statusline_command(env, previous=None):
    """Our status-line command. An existing one is wrapped, not hidden: its command text stays in
    settings.json word for word, so the plugin that owns it (ponytail, caveman, …) still finds its
    script there, and 'off' can restore it exactly."""
    script = shlex.quote(str(data_dir(env) / "statusline.py"))   # quoted: paths may contain spaces
    if previous:
        return f"python3 {script} statusline-chain {shlex.quote(previous)}"
    return f"python3 {script} statusline"


def _wrapped_command(command):
    """The original command wrapped inside our chain command, or None."""
    try:
        words = shlex.split(command or "")
    except ValueError:
        return None
    if "statusline-chain" in words and words.index("statusline-chain") + 1 < len(words):
        return words[words.index("statusline-chain") + 1]
    return None


def _project_statusline(cwd):
    """A status line set by this project's own settings (it wins over the user one), or None."""
    root = Path(repo_root(cwd) or cwd) if cwd else None
    for name in ("settings.local.json", "settings.json"):
        try:
            if root and json.loads((root / ".claude" / name).read_text()).get("statusLine"):
                return root / ".claude" / name
        except Exception:
            pass
    return None


def _is_ours(statusline_setting):
    return "statusline.py statusline" in str((statusline_setting or {}).get("command", ""))


def _plugin_config(env):
    try:
        return json.loads((data_dir(env) / "config.json").read_text())
    except Exception:
        return {}


def _save_plugin_config(env, cfg):
    p = data_dir(env) / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, cfg)


def _read_settings(path):
    """(settings dict, error) — never guesses at a file it can't parse."""
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, f"{path} isn't plain JSON (comments or a typo?) — not changed"
    if not isinstance(data, dict):
        return None, f"{path} isn't a JSON object — not changed"
    return data, None


def _backup(path):
    if not path.exists():
        return None
    b = path.with_name(path.name + time.strftime(".wf-backup-%Y%m%d-%H%M%S"))
    b.write_bytes(path.read_bytes())
    return b


def statusline_install(env, cwd=None):
    """Add the wf status line to Claude Code's user settings. Keeps every other setting, backs the
    file up first, and keeps an existing status line (e.g. ponytail) by showing both."""
    install_statusline(env)
    path = claude_dir(env) / "settings.json"
    data, err = _read_settings(path)
    if err:
        return f"status line {err}. Nothing else was touched."
    current = data.get("statusLine")
    if _is_ours(current):
        return "status line already installed — nothing changed. Remove it with /wf statusline off."
    backup = _backup(path)
    cfg = _plugin_config(env)
    if current and current.get("command"):
        cfg["previous_statusline"] = current
        data["statusLine"] = dict(current, type="command",
                                  command=_statusline_command(env, current["command"]))   # keeps padding etc.
        what = "installed next to your existing status line (kept, shown first)"
    else:
        cfg.pop("previous_statusline", None)
        data["statusLine"] = {"type": "command", "command": _statusline_command(env)}
        what = "installed"
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, data, indent=2)
    _save_plugin_config(env, cfg)
    override = _project_statusline(cwd)
    note = (f" Note: this project sets its own status line in {override}, which wins over yours here — "
            "the WF badge won't show in this project unless you remove it there." if override else "")
    return (f"status line {what} in {path}" + (f" (backup: {backup.name})" if backup else "") +
            ". You'll see [WF P3 · standard] under the prompt while the skin is on (new session if it "
            "doesn't appear). Undo: /wf statusline off." + note)


def statusline_remove(env):
    path = claude_dir(env) / "settings.json"
    data, err = _read_settings(path)
    if err:
        return f"status line {err}."
    if not _is_ours(data.get("statusLine")):
        return "status line not installed — nothing changed."
    backup = _backup(path)
    cfg = _plugin_config(env)
    saved = cfg.pop("previous_statusline", None)
    current = data["statusLine"]
    wrapped = _wrapped_command(current.get("command"))
    if wrapped is not None:
        # the command in settings.json is the truth (another plugin may have fixed its path inside it)
        previous = dict(current, command=wrapped)
        if saved and saved.get("command") == wrapped:
            previous = saved
    else:
        previous = None
    if previous:
        data["statusLine"] = previous
    else:
        data.pop("statusLine", None)
    _atomic_write(path, data, indent=2)
    _save_plugin_config(env, cfg)
    return ("status line removed" + (", your previous one is back" if previous else "") +
            (f" (backup: {backup.name})" if backup else "") + ".")


def statusline_chain(raw_stdin, env, previous=None):
    """Status line = the user's previous status line (same input), then ours."""
    if previous is None:
        previous = (_plugin_config(env).get("previous_statusline") or {}).get("command")
    before = ""
    if previous:
        try:
            before = subprocess.run(previous, shell=True, input=raw_stdin, capture_output=True, text=True,
                                    timeout=3).stdout.rstrip("\n")
        except Exception:
            before = ""
    try:
        ours = statusline(json.loads(raw_stdin or "{}"), env)
    except Exception:
        ours = ""
    return " ".join(x for x in (before, ours) if x)


# ---------------------------------------------------------------- /wf help (shown to the user only)

HELP_GUIDE = """help — everyday use
  /wf on              switch on for this project (default level: standard)
  /wf pause · resume  go quiet for a side task · continue where you were
  /wf status          where am I: P0 ✓ · P1 ✓ · P2 ⚠ skipped · P3 70%
  /wf off             fully off for this project
  At a gate: reply "approved" (or "start Phase 7") → next phase
  Rarely:  /wf strict · /wf 4 (go back) · /wf new · /wf dirs · /wf default · /wf statusline
  More: /wf help <command>, e.g. /wf help strict · full guide: README → 'Quick start'"""

HELP_TOPICS = {
    "on": "/wf on [level] — switch the skin on for this project and branch.\n"
          "  Claude gets the workflow spine once; phases then move on your approvals.\n"
          "  Example: /wf on   ·   /wf on strict (for auth, payments, schema work)",
    "off": "/wf off — fully off for this project; the current phase is forgotten.\n"
           "  Use pause instead if you want to come back to the same phase.\n"
           "  Example: /wf off",
    "pause": "/wf pause — go quiet (no rules, no gates, no guard) but remember the phase.\n"
             "  Good for a spike, a side question or an unrelated quick fix.\n"
             "  Example: /wf pause … do the side task … /wf resume",
    "resume": "/wf resume — switch back on at the phase you paused in.\n"
              "  Example: /wf resume",
    "status": "/wf status — level, current phase and the timeline of this feature.\n"
              "  ✓ approved · ⚠ skipped (left without an approved gate) · % = gate checklist.\n"
              "  Example: /wf status  →  P0 ✓ · P1 ✓ · P2 ⚠ skipped · P3 70% (gate)",
    "levels": "Levels — how strict the skin is (switch any time):\n"
              "  lite: every-phase rules only, no phases (docs, typos, config tweaks)\n"
              "  standard: phases + gates + checklist % (normal features — the default)\n"
              "  strict: + extra turn to fill missing items, merges blocked until Phase 10\n"
              "          (auth, payments, database schema, personal data, public APIs)\n"
              "  Example: /wf strict   ·   /wf default standard",
    "gate": "Gates — Claude ends a phase with its checklist lines and [[gate P3]].\n"
            "  You see: WF ▸ Gate P3 reached · checklist 8/10 (80%) · missing: …\n"
            "  Read the missing list, then reply approved / looks good / proceed → next phase.\n"
            "  Anything with but, change or a question mark is not an approval.\n"
            "  Example: approved   ·   start Phase 7 (after the Phase 6 gate)",
    "new": "/wf new — start a new feature: back to the tier check, timeline cleared.\n"
           "  Brainstorming does this for you; on a branch it makes that branch its own feature.\n"
           "  Example: /wf new",
    "phase": "/wf <0-10> — jump to a phase. Mainly to go back on purpose (a loop-back),\n"
             "  e.g. when Phase 5 sends the plan back to Phase 4. Skipped phases show ⚠.\n"
             "  Example: /wf 4",
    "dirs": "/wf dirs <spec> <plan> — your own spec/plan folders (relative to the repo root),\n"
            "  if they aren't docs/superpowers/specs|plans or docs/specs|plans.\n"
            "  Example: /wf dirs design/specs design/plans   ·   /wf dirs (show current)",
    "default": "/wf default <level> — the level /wf on uses on this machine.\n"
               "  Example: /wf default standard",
    "statusline": "/wf statusline — once per machine: shows [WF P3 70% · ✓✓⚠ · standard] under the prompt.\n"
                  "  It edits ~/.claude/settings.json for you (backup first, other settings kept);\n"
                  "  an existing status line (ponytail, caveman, your own) is kept word for word and\n"
                  "  shown first.\n"
                  "  Example: /wf statusline   ·   /wf statusline off (removes it, restores yours)",
}
HELP_TOPICS.update({lvl: HELP_TOPICS["levels"] for lvl in LEVELS})
HELP_TOPICS.update({"approve": HELP_TOPICS["gate"], "approved": HELP_TOPICS["gate"]})


def help_text(topic=None):
    if not topic:
        return HELP_GUIDE
    if topic.isdecimal():
        topic = "phase"
    return HELP_TOPICS.get(topic) or f"no help for '{topic}'. Try /wf help (everyday use)."


# ---------------------------------------------------------------- /wf commands

CMD_RE = re.compile(r"^\s*/wf(?::wf)?(?:\s+(.*))?\s*$", re.I | re.S)


def parse_command(prompt):
    m = CMD_RE.match(prompt or "")
    if not m:
        return None
    args = (m.group(1) or "").split()          # case kept: '/wf dirs' takes folder names
    if not args:
        return ("status", [])
    if args[0].isdecimal() and args[0].isascii():
        return ("phase", [args[0]])
    cmd = args[0].lower()
    return (cmd, args[1:] if cmd == "dirs" else [a.lower() for a in args[1:]])


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
            n, why = guess_phase(cwd, state.get("completed_at") or 0, state.get("dirs"))
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
    if cmd == "help":
        return None, HELP_SHOWN
    if cmd == "dirs":
        if len(args) == 2:
            state["dirs"] = {"spec": args[0], "plan": args[1]}
            return state, f"{tell}spec folder `{args[0]}`, plan folder `{args[1]}` (relative to the repo root)."
        cur = state.get("dirs") or {k: " or ".join(v) for k, v in DEFAULT_DIRS.items()}
        return None, f"{tell}spec folder {cur['spec']}, plan folder {cur['plan']}. Change: `/wf dirs <spec> <plan>`."
    if cmd == "statusline":
        msg = statusline_remove(env) if args[:1] == ["off"] else statusline_install(env, cwd)
        return None, tell + msg
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
        store.unfollow(cwd, state)
        new_feature(state)
        state.update(phase=0, injected=0)
        lead = f"{tell}new feature — starting at the tier check.\n\n"
        return state, lead + skin_context(state, env, cwd, budget=LIMIT - len(lead))
    return None, "Show the user in one line: unknown /wf command. " + HELP


# ---------------------------------------------------------------- per-phase checklists
# What each gate must cover, from Claude-Workflows-Best-Practices.md. The hook never interprets
# words in any language. It decides only from fixed tokens and exact text:
#   - `- <label>: "<passage>"`  the passage is searched for, verbatim, in the spec/plan file
#   - `- <label>: n/a — <why>`  not applicable (the reason may be in any language)
#   - `- <label>: missing`      not done
# Anything else on a label's line is a claim that the hook reports as claimed, not checked.
# It measures coverage, not quality: reading the gate stays the user's job.

# The labels live in the full doc: each phase ends with a line
#   **Gate checklist:** item · item *(file)* · …
# so the doc stays the single source of the rules (a project's own copy wins). Items marked (file)
# must be backed by a passage quoted from the spec/plan file.

GATE_LINE = re.compile(r"^\*\*Gate checklist:\*\*\s*(.+)$", re.M)
EXEC_RECORD_RE = re.compile(r"^#+\s*Execution record", re.M | re.I)   # the heading the doc tells Claude to write


def checks_from_doc(doc_text, n):
    """[(label, checked_in_file)] from phase n's 'Gate checklist' line in the doc ([] if it has none)."""
    m = GATE_LINE.search(phase_section(doc_text or "", n))
    if not m:
        return []
    items = []
    for raw in m.group(1).split(" · "):
        is_file = "(file)" in raw
        label = re.sub(r"\s*\*?\(file\)\*?\s*$", "", raw).strip()
        if label:
            items.append((label, is_file))
    return items


def _bundled_checks():
    try:
        doc = (Path(__file__).resolve().parent.parent / DOC).read_text(encoding="utf-8")
    except OSError:
        return {}
    return {n: checks_from_doc(doc, n) for n in range(0, 11)}


CHECKS = _bundled_checks()   # the plugin's own doc; used when a project's doc has no checklist lines


def items_for(n, env, cwd):
    return checks_from_doc(read_doc(DOC, env, cwd), n) or CHECKS.get(n, [])


# Phases whose gate claims are cross-checked against a file (the others are judged from the message).
DEFAULT_DIRS = {"spec": ("docs/superpowers/specs", "docs/specs"), "plan": ("docs/superpowers/plans", "docs/plans")}
PHASE_FILES = {3: "spec", 4: "plan", 6: "plan", 7: "plan"}
MAX_FILE = 5_000_000   # bytes; a bigger spec/plan is reported as too large to check, never half-read


def search_roots(cwd):
    """This checkout, plus the main checkout when cwd is a linked worktree: gitignored specs and
    plans exist only in the main checkout (the docs say to pass them by absolute path)."""
    roots = [Path(repo_root(cwd) or cwd)]
    common = Path(repo_identity(cwd)[0])
    if common.name == ".git" and common.parent not in roots:
        roots.append(common.parent)
    return roots


def _is_text(p):
    try:
        with open(p, "rb") as f:
            return b"\0" not in f.read(8192)
    except OSError:
        return False


def doc_files(kind, cwd, dirs=None, since=0):
    """[(mtime, path)] of the spec or plan files (any text file, any extension) changed after `since`
    ('/wf dirs' overrides the folders). Hidden and binary files are skipped."""
    folders = ((dirs or {}).get(kind),) if (dirs or {}).get(kind) else DEFAULT_DIRS[kind]
    out = []
    for root in search_roots(cwd):
        for d in folders:
            for p in (root / d).glob("*"):
                try:
                    if (not p.name.startswith(".") and p.is_file() and p.stat().st_mtime > since
                            and _is_text(p)):
                        out.append((p.stat().st_mtime, p))
                except OSError:
                    pass
    return sorted(out)


NA = re.compile(r"^\W*n/?a(\W|$)", re.I)            # fixed token, not a word list
MISSING = re.compile(r"^\W*missing(\W|$)", re.I)    # fixed token, not a word list


def checklist_lines(message):
    """{label(lower): value} for lines like '- label: value' (outside code fences)."""
    out, fence = {}, False
    for line in (message or "").splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else re.match(r"^\s*(?:[-*•]|\d+[.)])?\s*\**\s*([^:*\n]{2,60}?)\s*\**\s*:\s*(.*)$", line)
        if m:
            out[m.group(1).strip().lower()] = m.group(2).strip()
    return out


# ---- quoted passages: exact text, compared after normalising only how it is written

QUOTE_PAIRS = (('"', '"'), ("\u201c", "\u201d"), ("\u201e", "\u201c"), ("\u201e", "\u201d"),
               ("\u00ab", "\u00bb"), ("\u00bb", "\u00ab"), ("\u2039", "\u203a"), ("\u300c", "\u300d"),
               ("\u300e", "\u300f"), ("`", "`"))
QUOTE_RE = re.compile("|".join(re.escape(a) + "(.+?)" + re.escape(b) for a, b in QUOTE_PAIRS))
MIN_QUOTE = 15   # characters, not counting spaces: long enough to point at real content

_CHAR_MAP = str.maketrans({**{c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"},
                           **{c: "'" for c in "\u2018\u2019\u201a\u201b\u2032"},
                           **{c: '"' for c in "\u201c\u201d\u201e\u201f\u00ab\u00bb\u2039\u203a\u2033"},
                           **{c: " " for c in "\u00a0\u2007\u202f\u200b\u2060\ufeff"}})
_LINE_MARK = re.compile(r"^[ \t]*(?:[#>|]+|[-*+](?=\s))[ \t]*", re.M)   # heading, quote, table, bullet marks
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def norm_text(text):
    """Text reduced to what it says, not how it is formatted: Unicode NFKC, case folded, typographic
    dashes/quotes/spaces made plain, Markdown marks (line prefixes, links, emphasis, table pipes)
    dropped and all whitespace, line breaks included, collapsed to one space. Language-blind."""
    import unicodedata
    t = unicodedata.normalize("NFKC", text or "").translate(_CHAR_MAP)
    t = _LINK.sub(r"\1", _LINE_MARK.sub("", t))
    t = re.sub(r"[*_`~|]", "", t)
    return re.sub(r"\s+", " ", t).casefold().strip()


def quotes_in(value):
    """The passages quoted on a checklist line, in order."""
    return [m for g in QUOTE_RE.findall(value or "") for m in (g if isinstance(g, tuple) else (g,)) if m]


def check_quotes(value, norm_file, used):
    """('found', key) or (reason, None) for a covered item's quoted passages. `used` holds the
    passages earlier items already used: each item must stand on a passage of its own."""
    qs = [norm_text(q) for q in quotes_in(value)]
    if not qs:
        return "no quote", None
    long_enough = [q for q in qs if len(q.replace(" ", "")) >= MIN_QUOTE]
    if not long_enough:
        return "quote too short", None
    fresh = [q for q in long_enough if q not in used]
    if not fresh:
        return "same quote as another item", None
    for q in fresh:
        if q in norm_file:
            return "found", q
    return "quote not in file", None


def score(n, message, file_text=None, items=None):
    """Score phase n's gate from Claude's checklist lines '- <label>: <value>'.
    An item counts when its value is `n/a …`, or — for a (file) item while a spec/plan file exists —
    a quoted passage found in that file, or — for any other item — any value except `missing`.
    Covered (file) items that fail the quote check are listed in `unverified` with the reason;
    items counted without a check are listed in `claimed`."""
    items = CHECKS.get(n, []) if items is None else items
    lines = checklist_lines(message)
    norm_file = norm_text(file_text) if file_text is not None else None
    found, missing, unverified, claimed, reasons, listed, used = 0, [], [], [], {}, 0, set()
    for label, is_file in items:
        value = lines.get(label.lower())
        if value is not None:
            listed += 1
        if not value or MISSING.match(value):
            missing.append(label)
        elif NA.match(value):
            found += 1
        elif is_file and norm_file is not None:
            why, key = check_quotes(value, norm_file, used)
            if key:
                used.add(key)
                found += 1
            else:
                unverified.append(label)
                reasons[label] = why
        else:
            found += 1
            claimed.append(label)
    return {"found": found, "total": len(items), "missing": missing, "unverified": unverified,
            "reasons": reasons, "claimed": claimed, "listed": listed}


def phase_doc(n, cwd, state=None):
    """{'name', 'text'} of the newest spec (P3) or plan (P4, P6, P7) file changed since this feature
    started ('text' is None when it is too large or unreadable), or None when there is none."""
    kind = PHASE_FILES.get(n)
    if not kind:
        return None
    state = state or {}
    files = doc_files(kind, cwd, state.get("dirs"), state.get("feature_start") or 0)
    if not files:
        return None
    p = files[-1][1]
    try:
        if p.stat().st_size > MAX_FILE:
            return {"name": p.name, "text": None, "why": "too large to check"}
        return {"name": p.name, "text": p.read_text(encoding="utf-8", errors="replace")}
    except OSError:
        return {"name": p.name, "text": None, "why": "unreadable"}


def phase_file(n, cwd, state=None):
    """Text of phase n's spec/plan file, or None."""
    d = phase_doc(n, cwd, state)
    return d and d["text"]


def checklist_instruction(n, items=None):
    items = CHECKS.get(n, []) if items is None else items
    if not items:
        return ""
    labels = [l for l, _ in items]
    files = [l for l, f in items if f]
    where = {"spec": "the spec", "plan": "the plan"}.get(PHASE_FILES.get(n), "the spec/plan")
    text = (f"At the Phase {n} gate, just before `[[gate P{n}]]`, list one line per checklist item, using these "
            f"exact labels: " + "; ".join(labels) + ". Format: `- <label>: <where it is covered>`, "
            "`- <label>: n/a — <why>` or `- <label>: missing`. Never list an item you did not do as covered.")
    if files:
        text += (f" For " + "; ".join(files) + f": the value must contain a passage copied word for word "
                 f"from {where} file, in double quotes (at least {MIN_QUOTE} characters, a different passage "
                 "for each item), e.g. `- " + files[0] + ": \"<exact sentence from the file>\" (section …)`. "
                 "The hook searches the file for that exact text.")
    return text


def gate_line(n, entry):
    if not entry.get("total"):
        return f"Gate P{n} reached · waiting for your approval"
    head = f"Gate P{n} reached · checklist {entry['found']}/{entry['total']} ({score_pct(entry)}%)"
    if not entry.get("listed"):
        return head + " · no checklist lines in the gate message"
    tail = []
    if entry["missing"]:
        tail.append("missing: " + ", ".join(entry["missing"]))
    by_reason = {}
    for label in entry.get("unverified") or []:
        by_reason.setdefault((entry.get("reasons") or {}).get(label, "not checked"), []).append(label)
    for why, labels in by_reason.items():
        tail.append(f"{why}: " + ", ".join(labels))
    if entry.get("file_note"):
        tail.append(entry["file_note"])
    elif entry.get("file"):
        tail.append(f"{entry.get('checked') or 0} quoted in {entry['file']}")
    if entry.get("claimed"):
        tail.append(f"{len(entry['claimed'])} claimed, not checked")
    tail.append("content not judged — your review")
    return head + " · " + " · ".join(tail)



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


START_RE = re.compile(r"^(?:ok(?:ay)?[,.]?\s+)?(?:let'?s\s+)?start\s+phase\s+(\d{1,2})[.!]?$", re.I)


def is_approval(text):
    t = (text or "").strip()
    if not t or len(t) > 80 or t.startswith("/"):
        return False
    return bool(APPROVE_RE.match(t)) and not VETO_RE.search(HARMLESS_NO.sub("", t))


def move_to(state, n):
    """Set the phase and keep the timeline honest: phases left without an approved gate are
    'skipped'; going back (a loop-back) forgets everything from the target phase on."""
    if state["phase"] is None and n is not None:
        state.update(timeline={}, feature_start=time.time())   # entering a feature from nothing
    old, tl = state["phase"], state.setdefault("timeline", {})
    if old is not None and n is not None:
        if n > old:
            for k in range(old, n):
                entry = tl.get(str(k), {})
                if entry.get("status") not in ("done", "combined"):
                    tl[str(k)] = dict(entry, status="skipped")
        elif n < old:
            for k in [k for k in tl if int(k) >= n]:
                del tl[k]
    state["phase"] = n


def new_feature(state):
    state.update(phase=None, gate_pending=None, injected=None, timeline={}, feature_start=time.time())


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
        elif e.get("status") == "combined":
            parts.append(f"P{k} … in the P{ph} gate")
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


SCORE_KEYS = ("found", "total", "missing", "unverified", "reasons", "claimed", "listed", "file", "file_note",
              "checked")


def on_stop(payload, env, store, cwd):
    state = store.load(cwd)
    if not engine_on(state):
        return None
    gate = gate_from_message(payload.get("last_assistant_message"))
    if gate is not None and state["phase"] is not None and gate < state["phase"]:
        # An earlier phase's marker is a recap, not a loop-back: going back is the user's call (/wf N).
        if state.get("gate_pending") is not None:
            state["gate_pending"] = None
            store.save(cwd, state)
        return output("Stop", None, f"Gate P{gate} marker at Phase {state['phase']} ignored (treated as a recap) "
                                    f"— to go back to Phase {gate}, type `/wf {gate}`")
    if gate != state.get("gate_pending") or (gate is not None and state["phase"] != gate):
        if gate is not None and state["phase"] != gate:
            old = state["phase"]
            move_to(state, gate)
            if old is not None and old < gate:
                # One message may close earlier phases too (brainstorming's first message is the Phase 1
                # summary and can carry the Phase 0 items): a fully covered earlier checklist rides on
                # this gate's approval instead of counting as skipped.
                tl = state["timeline"]
                for k in range(old, gate):
                    r = score(k, payload.get("last_assistant_message"), None, items_for(k, env, cwd))
                    if r["listed"] and r["found"] == r["total"]:
                        tl[str(k)] = dict(r, status="combined")
        state["gate_pending"] = gate
        store.save(cwd, state)
    if gate is None:
        return None
    items = items_for(gate, env, cwd)
    doc = phase_doc(gate, cwd, state)
    r = score(gate, payload.get("last_assistant_message"), doc and doc["text"], items)
    if any(f for _, f in items) and gate in PHASE_FILES:
        if doc is None:
            r.update(file_note=f"no {PHASE_FILES[gate]} file changed since this feature started — quotes not checked")
        else:
            r.update(file=doc["name"],
                     file_note=f"{doc['name']} {doc['why']} — quotes not checked" if doc.get("why") else None,
                     checked=sum(1 for l, f in items if f and l not in r["missing"] + r["unverified"]
                                 + r["claimed"]) if doc["text"] is not None else 0)
    tl = state.setdefault("timeline", {})
    prev = tl.get(str(gate), {})
    if not r["listed"] and prev.get("listed"):
        r = {k: prev[k] for k in SCORE_KEYS if k in prev}   # keep last real score
    missing = r["missing"] + r["unverified"]
    entry = dict(prev, **r)
    tl[str(gate)] = entry
    out = output("Stop", None, gate_line(gate, entry))
    body = (payload.get("last_assistant_message") or "").rsplit("[[gate", 1)[0].rstrip()
    if (state["level"] == "strict" and missing and not entry.get("nudged")
            and not payload.get("stop_hook_active") and not body.endswith("?")):
        entry["nudged"] = True
        out["decision"] = "block"
        out["reason"] = (f"Workflow checklist for the Phase {gate} gate is incomplete. Missing: "
                         f"{', '.join(missing)}. Do each one (or decide it is n/a, with the reason); for a "
                         "(file) item, quote the exact passage from the file. Then end "
                         f"with the checklist lines and `[[gate P{gate}]]` again. {checklist_instruction(gate, items)} "
                         "(This reminder comes once per gate.)")
    store.save(cwd, state)
    return out


def approve(state, env, cwd):
    gate = state["gate_pending"]
    tl = state.setdefault("timeline", {})
    tl[str(gate)] = dict(tl.get(str(gate), {}), status="done")
    for k, e in tl.items():
        if e.get("status") == "combined" and int(k) < gate:
            e["status"] = "done"
    if gate >= 10:
        state.update(phase=None, gate_pending=None, injected=None, completed_at=time.time(), timeline={})
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
                       "New feature (brainstorming started). Brainstorming covers Phases 0–3. Its first message "
                       "is the Phase 1 summary: name the tier there and end it with the Phase 0 and Phase 1 "
                       "checklist lines and one `[[gate P1]]` — a single gate for both. State the Phase 2 exit "
                       "answers before its approaches message (`[[gate P2]]`); its design doc is the Phase 3 "
                       "spec (`[[gate P3]]`). Phase 0 checklist labels: "
                       + "; ".join(l for l, _ in items_for(0, env, cwd)) + ". Format of each line: "
                       "`- <label>: <where covered>`, `- <label>: n/a — <why>` or `- <label>: missing`.")


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
            "Before the workspace is deleted, copy the ledger's Ruling / parked / minor (deferred) / \"no reachable "
            "spec\" lines into the plan under `## Execution record`.")
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


def guess_phase(cwd, since=0, dirs=None):
    """Best guess of the phase from spec/plan files changed after `since` (a finished feature's
    files don't count): (phase, evidence) or (None, '')."""
    plans, specs = doc_files("plan", cwd, dirs, since), doc_files("spec", cwd, dirs, since)
    for _, p in plans:
        try:
            if EXEC_RECORD_RE.search(p.read_text(encoding="utf-8", errors="replace")):
                return 8, f"plan {p} has an Execution record"
        except OSError:
            pass
    if plans:
        return 5, f"plan {plans[-1][1]} exists"
    if specs:
        return 4, f"spec {specs[-1][1]} exists"
    return None, ""


# ---------------------------------------------------------------- guards

DEFAULT_BRANCHES = ("main", "master")
_GIT = r"\bgit(?:\s+-(?:C|c)\s+\S+)*\s+"


def _hits_default(ref, branch):
    ref = ref.lstrip("+").split(":")[-1]
    if ref.startswith("refs/heads/"):  # (str.removeprefix needs Python 3.9; keep 3.8 working)
        ref = ref[len("refs/heads/"):]
    if ref in ("HEAD", "@"):
        ref = branch
    return ref in DEFAULT_BRANCHES


def _segments(command):
    """Shell command split into the simple commands it runs, in order (&&, ||, ;, |, newlines)."""
    return [seg.strip() for seg in re.split(r"&&|\|\||[;|\n]", command or "") if seg.strip()]


def _branch_after(seg, branch):
    """The branch checked out after this simple command (follows `git checkout/switch`)."""
    m = re.search(_GIT + r"(checkout|switch)\b(.*)", seg)
    if not m:
        return branch
    words = m.group(2).split()
    if "--" in words or not words:                       # `git checkout main -- file`: restores a file only
        return branch
    for flag in ("-b", "-B", "-c", "-C", "--orphan"):     # creates a new branch
        if flag in words and words.index(flag) + 1 < len(words):
            return words[words.index(flag) + 1]
    args = [w for w in words if not w.startswith("-")]
    return args[0] if args else branch


def guard_reason(command, branch):
    """Why this shell command would change the default branch directly, or '' if it wouldn't.
    Follows branch switches inside the command (`git checkout main && git merge feat`)."""
    for seg in _segments(command):
        reason = _segment_reason(seg, branch)
        if reason:
            return reason
        branch = _branch_after(seg, branch)
    return ""


def _segment_reason(c, branch):
    on_default = branch in DEFAULT_BRANCHES
    if re.search(r"\bgh\s+pr\s+merge\b", c):
        return "`gh pr merge` merges a pull request"
    if on_default and re.search(_GIT + r"merge(?![-\w])", c):
        return f"`git merge` on `{branch}` merges into the default branch"
    if on_default and re.search(_GIT + r"commit\b", c):
        return f"`git commit` on `{branch}` commits straight to the default branch (work on a branch)"
    for m in re.finditer(_GIT + r"pull\b(.*)", c):
        refs = [a for a in m.group(1).split() if not a.startswith("-")][1:]
        if on_default and refs and not all(_hits_default(r, branch) for r in refs):
            return f"`git pull` of another branch on `{branch}` merges it into the default branch"
    for m in re.finditer(_GIT + r"push\b(.*)", c):
        words = m.group(1).split()
        if "--all" in words or "--mirror" in words:
            return "`git push --all/--mirror` pushes the default branch too"
        refs = [a for a in words if not a.startswith("-")][1:]  # after the remote
        if any(_hits_default(r, branch) for r in refs):
            return "`git push` to the default branch"
        if not refs and on_default:
            return f"`git push` on `{branch}` pushes the default branch"
    return ""


def on_bash(payload, env, store, cwd):
    state = store.load(cwd)
    if state["enabled"] != "on":
        return None
    reason = guard_reason((payload.get("tool_input") or {}).get("command"), current_branch(cwd))
    if not reason:
        return None
    strict = state["level"] == "strict" and (state["phase"] is None or state["phase"] < 10)
    why = (f"Workflow merge guard: {reason}. Work happens on a branch, changes land through a PR, and "
           f"merging is the last step of Phase 10 (after deploy + health check).")
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
        cmd, args = parsed
        if cmd == "help":
            show = help_text(args[0] if args else None)
        elif cmd == "statusline":
            show = text.split(": ", 1)[1]
        elif text.startswith("Show the user in one line: unknown"):
            show = f"unknown command '/wf {cmd}'. Type /wf help for the everyday commands."
        else:
            show = show_status(new or store.load(cwd))
        return output("UserPromptSubmit", text, show)
    start = START_RE.match((payload.get("prompt") or "").strip())
    if engine_on(state) and start:
        n, gate = int(start.group(1)), state.get("gate_pending")
        if gate is None or n != gate + 1:
            where = "no gate is pending" if gate is None else f"the pending gate is Phase {gate}"
            return output("UserPromptSubmit",
                          f"wf: the user asked to start Phase {n}, but {where}; phases move one at a time"
                          + (f" (next is Phase {gate + 1})" if gate is not None else "") +
                          ". Tell the user in one line; to jump anyway they can type `/wf " + str(n) + "`.",
                          f"start Phase {n} not applied — {where}")
        payload = dict(payload, prompt="approved")
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


READ_ONLY_COMMANDS = ("help", "status", "statusline")


def handle(event, payload, env):
    cwd = payload.get("cwd") or env.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    fn = HANDLERS.get(event)
    if not fn:
        return None
    repo_identity.cache_clear()
    store = Store(env)
    followed = None
    if store.dir.is_dir() and not store.path(cwd).exists() and store.pointer(cwd).exists():
        with store.locked(cwd):
            followed = store.follow(cwd)
    out = _handle(event, payload, env, store, cwd, fn)
    if followed:
        st = store.load(cwd)
        line = (f"WF ▸ branch changed {followed} → {repo_identity(cwd)[1]} · skin follows "
                f"({describe(st).split(', ', 1)[-1]})")
        out = out or {}
        out["systemMessage"] = line + ("\n" + out["systemMessage"] if out.get("systemMessage") else "")
    return out


def _handle(event, payload, env, store, cwd, fn):
    # Fast path: the skin was never used here, or is off, and this isn't a /wf command — nothing to do.
    # No lock, no files, no further git calls (this runs before every Bash tool call in every project).
    parsed = parse_command(payload.get("prompt", "")) if event == "UserPromptSubmit" else None
    if parsed and parsed[0] in READ_ONLY_COMMANDS:
        return fn(payload, env, store, cwd)          # nothing to change: no lock, no files
    if not parsed:
        saved = store.peek(cwd) if store.dir.is_dir() else None  # never used on this machine: no git at all
        if not saved or saved.get("enabled", "off") == "off":
            if event == "SessionStart":
                install_statusline(env)
            return None
    with store.locked(cwd):
        return fn(payload, env, store, cwd)


def statusline(payload, env):
    cwd = (payload.get("workspace") or {}).get("current_dir") or payload.get("cwd") or os.getcwd()
    repo_identity.cache_clear()
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
        raw = sys.stdin.read()
        if event in ("statusline", "statusline-chain"):
            # The status line runs outside the plugin: our state dir is this script's own dir.
            env.setdefault("CLAUDE_PLUGIN_DATA", str(Path(__file__).resolve().parent))
            if event == "statusline-chain":
                line = statusline_chain(raw, env, argv[2] if len(argv) > 2 else None)
            else:
                line = statusline(json.loads(raw or "{}"), env)
            print(line, end="")
            return
        payload = json.loads(raw or "{}")
        out = handle(event, payload, env)
        if out:
            print(json.dumps(out))
    except Exception:
        pass  # never break the session


if __name__ == "__main__":
    main(sys.argv)
