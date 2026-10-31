#!/usr/bin/env python3
"""wf — the Claude-Workflows "invisible skin" for Claude Code.

One script for every hook. Usage (from hooks/hooks.json):  python3 wf.py <HookEvent>
Reads the hook's JSON on stdin, prints hook JSON on stdout (or nothing). Never fails loudly:
any error means "do nothing", so a broken skin can never break a session.

State lives on this machine only: $CLAUDE_PLUGIN_DATA/state/<sha256(repo+branch)>.json
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

LEVELS = ("lite", "standard", "strict")
DEFAULT_LEVEL = "standard"
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
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return (str(Path(cwd).resolve()), "")
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or ""
    return (str(Path(common).resolve()), branch)


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
                "gate_pending": None, "injected": None}

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
        with open(str(p) + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _atomic_write(p, state)


def _atomic_write(path, obj):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- output helpers

def output(event, text):
    if not text:
        return None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def describe(state):
    if state["enabled"] == "off":
        return "off"
    ph = state["phase"]
    where = "no phase yet" if ph is None else f"Phase {ph} ({PHASE_NAMES.get(ph, '?')})"
    return f"{state['enabled']}, level {state['level']}, {where}"


def skin_context(state, env, cwd, with_phase=True):
    """What Claude needs while the skin is on: spine (or lite rules) + current phase section."""
    spine = read_doc(SPINE, env, cwd)
    if state["level"] == "lite":
        return "Claude-Workflows skin (lite): apply these rules in every step.\n\n" + every_phase_rules(spine)
    parts = ["Claude-Workflows skin is on (level %s). This project follows the phased workflow below; "
             "the user clears every exit gate. When you reach a phase's exit gate, end your message with "
             "the line `[[gate P<n>]]` (n = the phase number) and wait for the user." % state["level"],
             spine]
    if state["level"] == "strict":
        parts.append("Strict level: run Phase 5 as one fresh-context subagent on the most capable model; "
                     "the Quick tier always needs the user's explicit confirmation.")
    if with_phase and state["phase"] is not None:
        parts.append(phase_context(state["phase"], env, cwd))
    return "\n\n".join(p for p in parts if p)


def phase_context(n, env, cwd):
    return (f"Current phase: {n} ({PHASE_NAMES.get(n, '?')}). Full rules for this phase:\n\n"
            + phase_section(read_doc(DOC, env, cwd), n))


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
    if args[0].isdigit():
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
        return state, f"{tell}workflow skin ON ({describe(state)}).\n\n" + skin_context(state, env, cwd)
    if cmd == "resume":
        if state["enabled"] == "off":
            return None, tell + "the skin is off — use `/wf on`."
        state["enabled"] = "on"
        return state, f"{tell}workflow skin resumed ({describe(state)}).\n\n" + skin_context(state, env, cwd)
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
        return None, f"{tell}workflow skin {describe(state)}."
    if cmd == "statusline":
        return None, "Show the user this, verbatim:\n\n" + statusline_snippet(env)
    if cmd == "phase":
        n = int(args[0])
        if not 0 <= n <= 10:
            return None, tell + "phases are 0–10. " + HELP
        if state["enabled"] == "off":
            state["enabled"] = "on"
        state.update(phase=n, gate_pending=None, injected=n)
        return state, f"{tell}moved to Phase {n} ({PHASE_NAMES[n]}).\n\n" + skin_context(state, env, cwd)
    if cmd == "new":
        if state["enabled"] == "off":
            state["enabled"] = "on"
        state.update(phase=0, gate_pending=None, injected=0)
        return state, f"{tell}new feature — starting at the tier check.\n\n" + skin_context(state, env, cwd)
    return None, "Show the user: unknown /wf command. " + HELP


# ---------------------------------------------------------------- hook handlers

def install_statusline(env):
    """Copy this script to the data dir: a path that survives plugin updates, for the status line."""
    try:
        dst = data_dir(env) / "statusline.py"
        src = Path(__file__).resolve()
        if src != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
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
        return output("UserPromptSubmit", text)
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
}


def handle(event, payload, env):
    cwd = payload.get("cwd") or env.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    fn = HANDLERS.get(event)
    return fn(payload, env, Store(env), cwd) if fn else None


def statusline(payload, env):
    cwd = (payload.get("workspace") or {}).get("current_dir") or payload.get("cwd") or os.getcwd()
    state = Store(env).load(cwd)
    if state["enabled"] == "off":
        return ""
    ph = "–" if state["phase"] is None else state["phase"]
    if state["enabled"] == "paused":
        return f"[WF ⏸ P{ph}]"
    return f"[WF P{ph} · {state['level']}]"


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
