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


# ================================================================ M2: phase engine

class TestGateMarker(unittest.TestCase):
    def test_marker_on_last_line(self):
        self.assertEqual(wf.gate_from_message("Spec ready.\n\n[[gate P3]]\n"), 3)
        self.assertEqual(wf.gate_from_message("done\n[[gate P10]]"), 10)

    def test_marker_not_last_line_or_in_fence_or_invalid(self):
        self.assertIsNone(wf.gate_from_message("[[gate P3]]\nmore text"))
        self.assertIsNone(wf.gate_from_message("example:\n```\n[[gate P3]]\n```"))
        self.assertIsNone(wf.gate_from_message("[[gate P11]]"))
        self.assertIsNone(wf.gate_from_message(""))
        self.assertIsNone(wf.gate_from_message(None))


class TestApproval(unittest.TestCase):
    def test_approvals(self):
        for t in ["approved", "Approved.", "looks good", "LGTM!", "proceed", "ok, proceed",
                  "yes", "go ahead", "approve", "sounds good, continue", "ok"]:
            self.assertTrue(wf.is_approval(t), t)

    def test_not_approvals(self):
        for t in ["looks good but change the title", "approved except step 3", "no",
                  "why did you pick sqlite?", "wait", "proceed, but first fix the typo",
                  "ok go run the tests and tell me what fails, then we redo the whole plan from scratch please",
                  "can you explain step 2", "/wf on", "don't proceed", "not yet"]:
            self.assertFalse(wf.is_approval(t), t)


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.e.prompt("/wf on")

    def tearDown(self):
        self.e.close()

    def stop(self, msg):
        return self.e.run("Stop", last_assistant_message=msg, stop_hook_active=False)

    def skill(self, name):
        return self.e.run("PreToolUse", tool_name="Skill", tool_input={"skill": name})


class TestPhaseEngine(EngineCase):
    def test_gate_then_approval_advances_one_phase(self):
        self.e.prompt("/wf 3")
        self.assertIsNone(self.stop("Here is the spec.\n[[gate P3]]"))
        self.assertEqual(self.e.state()["gate_pending"], 3)
        out = self.e.prompt("approved")
        s = self.e.state()
        self.assertEqual((s["phase"], s["gate_pending"]), (4, None))
        self.assertIn("## Phase 4", ctx(out))
        self.assertIn("approved", ctx(out).lower())

    def test_approval_without_pending_gate_does_nothing(self):
        self.e.prompt("/wf 3")
        self.assertIsNone(self.e.prompt("approved"))
        self.assertEqual(self.e.state()["phase"], 3)

    def test_turn_without_marker_clears_pending_gate(self):
        self.e.prompt("/wf 3")
        self.stop("spec\n[[gate P3]]")
        self.e.prompt("why sqlite?")
        self.stop("Because ... (answer to side question)")
        self.assertIsNone(self.e.state()["gate_pending"])
        self.assertIsNone(self.e.prompt("ok"))
        self.assertEqual(self.e.state()["phase"], 3)

    def test_non_approval_keeps_phase(self):
        self.e.prompt("/wf 3")
        self.stop("spec\n[[gate P3]]")
        self.assertIsNone(self.e.prompt("looks good but rename the table"))
        self.assertEqual(self.e.state()["phase"], 3)

    def test_marker_moves_phase_to_marker_phase(self):
        self.e.prompt("/wf 0")
        self.stop("Context summary...\n[[gate P1]]")
        self.e.prompt("approved")
        self.assertEqual(self.e.state()["phase"], 2)

    def test_final_gate_completes_feature(self):
        self.e.prompt("/wf 10")
        self.stop("Deployed, healthy.\n[[gate P10]]")
        out = self.e.prompt("approved")
        s = self.e.state()
        self.assertIsNone(s["phase"])
        self.assertEqual(s["enabled"], "on")
        self.assertIn("complete", ctx(out).lower())

    def test_stop_never_blocks_and_is_silent_when_off_paused_or_lite(self):
        self.e.prompt("/wf 3")
        self.e.prompt("/wf pause")
        self.stop("x\n[[gate P3]]")
        self.assertIsNone(self.e.state()["gate_pending"])
        self.e.prompt("/wf lite")
        self.stop("x\n[[gate P3]]")
        self.assertIsNone(self.e.state()["gate_pending"])

    def test_approval_ignored_when_paused(self):
        self.e.prompt("/wf 3")
        self.stop("x\n[[gate P3]]")
        self.e.prompt("/wf pause")
        self.assertIsNone(self.e.prompt("approved"))


class TestSkillMapping(EngineCase):
    def test_brainstorming_starts_feature(self):
        out = self.skill("superpowers:brainstorming")
        self.assertEqual(self.e.state()["phase"], 0)
        self.assertIn("Task Tiers", ctx(out))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    def test_brainstorming_mid_feature_does_not_reset(self):
        self.e.prompt("/wf 2")
        self.skill("superpowers:brainstorming")
        self.assertEqual(self.e.state()["phase"], 2)

    def test_typed_skill_via_expansion(self):
        out = self.e.run("UserPromptExpansion", command_name="superpowers:brainstorming", command_args="")
        self.assertEqual(self.e.state()["phase"], 0)
        self.assertIn("Task Tiers", ctx(out))

    def test_writing_plans_before_spec_approved_warns(self):
        self.e.prompt("/wf 2")
        out = self.skill("superpowers:writing-plans")
        self.assertIn("not approved", ctx(out))
        self.assertEqual(self.e.state()["phase"], 2)

    def test_writing_plans_after_spec_enters_phase_4(self):
        self.e.prompt("/wf 3")
        out = self.skill("superpowers:writing-plans")
        self.assertEqual(self.e.state()["phase"], 4)
        self.assertIn("## Phase 4", ctx(out))
        self.assertIn("execution method", ctx(out))

    def test_executor_before_phase_6_warns(self):
        self.e.prompt("/wf 4")
        for name in ("superpowers:subagent-driven-development", "superpowers:executing-plans"):
            out = self.skill(name)
            self.assertIn("Phase 5", ctx(out))
            self.assertEqual(self.e.state()["phase"], 4)

    def test_executor_after_phase_6_enters_7(self):
        self.e.prompt("/wf 6")
        out = self.skill("superpowers:subagent-driven-development")
        self.assertEqual(self.e.state()["phase"], 7)
        self.assertIn("Execution record", ctx(out))

    def test_finishing_before_phase_10_holds(self):
        self.e.prompt("/wf 7")
        out = self.skill("superpowers:finishing-a-development-branch")
        self.assertIn("Phases 8", ctx(out))

    def test_debugging_reminds_tier_and_branch(self):
        out = self.skill("superpowers:systematic-debugging")
        self.assertIn("branch", ctx(out))

    def test_unrelated_and_own_skills_ignored(self):
        self.assertIsNone(self.skill("pdf"))
        self.assertIsNone(self.skill("wf:wf"))

    def test_skills_ignored_when_paused_or_lite(self):
        self.e.prompt("/wf pause")
        self.assertIsNone(self.skill("superpowers:brainstorming"))
        self.e.prompt("/wf lite")
        self.assertIsNone(self.skill("superpowers:brainstorming"))

    def test_same_section_not_injected_twice_in_a_row(self):
        self.e.prompt("/wf 3")
        self.skill("superpowers:writing-plans")
        out = self.skill("superpowers:writing-plans")
        self.assertNotIn("## Phase 4", ctx(out))


class TestPhaseGuess(unittest.TestCase):
    def guess_for(self, files):
        e = Env()
        try:
            for rel, text in files.items():
                p = e.repo / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            out = e.prompt("/wf on")
            return e.state()["phase"], ctx(out)
        finally:
            e.close()

    def test_no_artifacts_no_guess(self):
        phase, text = self.guess_for({})
        self.assertIsNone(phase)
        self.assertNotIn("Looks like", text)

    def test_spec_only(self):
        phase, text = self.guess_for({"docs/superpowers/specs/2026-11-01-x-design.md": "spec"})
        self.assertEqual(phase, 4)
        self.assertIn("Looks like Phase 4", text)

    def test_plan_exists(self):
        phase, _ = self.guess_for({"docs/superpowers/specs/a-design.md": "s",
                                   "docs/superpowers/plans/2026-11-01-x.md": "plan"})
        self.assertEqual(phase, 5)

    def test_plan_with_execution_record(self):
        phase, _ = self.guess_for({"docs/plans/2026-11-01-x-plan.md": "p\n## Execution record\n- Ruling: x"})
        self.assertEqual(phase, 8)
