"""Tests for scripts/wf.py — run with: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import wf  # noqa: E402


def git_repo(path, branch="feature-x"):
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    if branch != "main":
        subprocess.run(["git", "-C", str(path), "checkout", "-q", "-b", branch], check=True)
    return path


class Env:
    """A temp repo + temp plugin data dir; runs hook events through wf.handle()."""

    def __init__(self, branch="feature-x"):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = git_repo(base / "repo", branch)
        self.data = base / "data"
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.data), "CLAUDE_PLUGIN_ROOT": str(ROOT),
                    "CLAUDE_PROJECT_DIR": str(self.repo)}

    def run(self, event, **payload):
        payload.setdefault("cwd", str(self.repo))
        payload.setdefault("session_id", "s1")
        payload["hook_event_name"] = event
        return wf.handle(event, payload, self.env)

    def prompt(self, text):
        return self.run("UserPromptSubmit", prompt=text)

    def state(self):
        return wf.Store(self.env).load(str(self.repo))

    def close(self):
        self.tmp.cleanup()


def ctx(out):
    """additionalContext text of a hook output (or '')."""
    if not out:
        return ""
    return out.get("hookSpecificOutput", {}).get("additionalContext", "")


class TestDocSections(unittest.TestCase):
    def setUp(self):
        self.doc = (ROOT / "Claude-Workflows-Best-Practices.md").read_text()

    def test_every_phase_has_a_section(self):
        for n in range(0, 11):
            text = wf.phase_section(self.doc, n)
            self.assertTrue(text.strip(), f"phase {n} empty")

    def test_phase_section_contains_its_heading_only(self):
        p4 = wf.phase_section(self.doc, 4)
        self.assertIn("## Phase 4", p4)
        self.assertNotIn("## Phase 5", p4)

    def test_phase_zero_is_tiers_plus_prereqs(self):
        p0 = wf.phase_section(self.doc, 0)
        self.assertIn("Task Tiers", p0)
        self.assertIn("Prerequisites", p0)

    def test_headings_inside_code_fences_are_ignored(self):
        doc = "## A\ntext\n```\n## Not a heading\n```\nmore\n## B\nb\n"
        secs = wf.split_sections(doc)
        self.assertEqual([h for h, _ in secs], ["## A", "## B"])
        self.assertIn("## Not a heading", secs[0][1])

    def test_every_section_fits_hook_limit(self):
        for n in range(0, 11):
            self.assertLess(len(wf.phase_section(self.doc, n)), 9500, n)


class TestCommandParsing(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(wf.parse_command("/wf on"), ("on", []))
        self.assertEqual(wf.parse_command("/wf on strict"), ("on", ["strict"]))
        self.assertEqual(wf.parse_command("/wf:wf pause"), ("pause", []))
        self.assertEqual(wf.parse_command("  /WF Status "), ("status", []))
        self.assertEqual(wf.parse_command("/wf"), ("status", []))
        self.assertEqual(wf.parse_command("/wf 5"), ("phase", ["5"]))
        self.assertIsNone(wf.parse_command("/wfoo on"))
        self.assertIsNone(wf.parse_command("please run /wf on"))


class TestStateAndCommands(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.close()

    def test_default_is_off_and_silent(self):
        self.assertEqual(self.e.state()["enabled"], "off")
        self.assertIsNone(self.e.run("SessionStart", source="startup"))
        self.assertIsNone(self.e.prompt("hello"))

    def test_on_enables_with_default_level_and_injects_spine(self):
        out = self.e.prompt("/wf on")
        s = self.e.state()
        self.assertEqual((s["enabled"], s["level"]), ("on", "standard"))
        self.assertIn("Phases — do → exit gate", ctx(out))  # compact spine injected

    def test_on_with_level(self):
        self.e.prompt("/wf on strict")
        self.assertEqual(self.e.state()["level"], "strict")

    def test_level_word_alone_switches_level_and_enables(self):
        self.e.prompt("/wf lite")
        s = self.e.state()
        self.assertEqual((s["enabled"], s["level"]), ("on", "lite"))

    def test_lite_injects_only_every_phase_rules(self):
        out = self.e.prompt("/wf on lite")
        self.assertIn("Absence ≠ confirmation", ctx(out))
        self.assertNotIn("Phases — do → exit gate", ctx(out))

    def test_pause_keeps_phase_and_goes_silent(self):
        self.e.prompt("/wf on")
        self.e.prompt("/wf 4")
        self.e.prompt("/wf pause")
        s = self.e.state()
        self.assertEqual((s["enabled"], s["phase"]), ("paused", 4))
        self.assertIsNone(self.e.run("SessionStart", source="compact"))
        self.e.prompt("/wf resume")
        s = self.e.state()
        self.assertEqual((s["enabled"], s["phase"]), ("on", 4))

    def test_off_clears_phase(self):
        self.e.prompt("/wf on")
        self.e.prompt("/wf 4")
        self.e.prompt("/wf off")
        s = self.e.state()
        self.assertEqual((s["enabled"], s["phase"]), ("off", None))

    def test_default_persists_for_new_projects(self):
        self.e.prompt("/wf default strict")
        other = Env()
        try:
            other.env["CLAUDE_PLUGIN_DATA"] = self.e.env["CLAUDE_PLUGIN_DATA"]
            other.prompt("/wf on")
            self.assertEqual(other.state()["level"], "strict")
        finally:
            other.close()

    def test_state_is_per_branch(self):
        self.e.prompt("/wf on")
        self.e.prompt("/wf 6")
        subprocess.run(["git", "-C", str(self.e.repo), "checkout", "-q", "-b", "other"], check=True)
        self.assertEqual(self.e.state()["enabled"], "off")

    def test_state_same_from_subdirectory(self):
        self.e.prompt("/wf on")
        sub = self.e.repo / "a" / "b"
        sub.mkdir(parents=True)
        self.assertEqual(wf.Store(self.e.env).load(str(sub))["enabled"], "on")

    def test_status_reports_without_changing(self):
        self.e.prompt("/wf on")
        out = self.e.prompt("/wf status")
        self.assertIn("standard", ctx(out))
        self.assertEqual(self.e.state()["enabled"], "on")

    def test_unknown_argument_reports_help(self):
        out = self.e.prompt("/wf banana")
        self.assertIn("/wf on", ctx(out))
        self.assertEqual(self.e.state()["enabled"], "off")

    def test_session_start_reinjects_spine_and_phase_when_on(self):
        self.e.prompt("/wf on")
        self.e.prompt("/wf 4")
        out = self.e.run("SessionStart", source="compact")
        self.assertIn("Phases — do → exit gate", ctx(out))
        self.assertIn("## Phase 4", ctx(out))

    def test_project_copy_of_doc_wins(self):
        (self.e.repo / "Claude-Workflows-Best-Practices.md").write_text(
            "## Phase 4 — Plan Writing\nCUSTOM PROJECT RULES\n")
        self.e.prompt("/wf on")
        out = self.e.prompt("/wf 4")
        self.assertIn("CUSTOM PROJECT RULES", ctx(out))

    def test_non_git_dir_works(self):
        d = tempfile.mkdtemp()
        out = wf.handle("UserPromptSubmit", {"prompt": "/wf on", "cwd": d, "session_id": "x"}, self.e.env)
        self.assertIn("on", ctx(out))

    def test_corrupt_state_file_is_treated_as_off(self):
        self.e.prompt("/wf on")
        store = wf.Store(self.e.env)
        Path(store.path(str(self.e.repo))).write_text("{not json")
        self.assertEqual(self.e.state()["enabled"], "off")


class TestStatusline(unittest.TestCase):
    def test_statusline_text(self):
        e = Env()
        try:
            self.assertEqual(wf.statusline({"cwd": str(e.repo)}, e.env), "")
            e.prompt("/wf on")
            e.prompt("/wf 4")
            self.assertEqual(wf.statusline({"cwd": str(e.repo)}, e.env), "[WF P4 · standard]")
            e.prompt("/wf pause")
            self.assertEqual(wf.statusline({"cwd": str(e.repo)}, e.env), "[WF ⏸ P4]")
        finally:
            e.close()

    def test_statusline_command_prints_snippet(self):
        e = Env()
        try:
            out = e.prompt("/wf statusline")
            self.assertIn('"statusLine"', ctx(out))
        finally:
            e.close()


class TestStatuslineInstall(unittest.TestCase):
    def test_on_installs_statusline_script_in_data_dir(self):
        e = Env()
        try:
            e.prompt("/wf on")
            script = e.data / "statusline.py"
            self.assertTrue(script.is_file())
            p = subprocess.run([sys.executable, str(script), "statusline"],
                               input=json.dumps({"workspace": {"current_dir": str(e.repo)}}),
                               capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
            self.assertEqual(p.stdout, "[WF P– · standard]")
        finally:
            e.close()


class TestCli(unittest.TestCase):
    def test_main_reads_stdin_and_prints_json(self):
        e = Env()
        try:
            env = dict(os.environ, **e.env)
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / "wf.py"), "UserPromptSubmit"],
                               input=json.dumps({"prompt": "/wf on", "cwd": str(e.repo), "session_id": "s"}),
                               capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("additionalContext", p.stdout)
        finally:
            e.close()

    def test_main_never_crashes_on_garbage(self):
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "wf.py"), "UserPromptSubmit"],
                           input="not json", capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")


if __name__ == "__main__":
    unittest.main()
