"""Tests for scripts/wf.py — run with: python3 -m unittest discover -s tests"""
import json
import os
import re
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
        wf.repo_identity.cache_clear()  # a real hook run is a fresh process; the cache lives one run
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
        wf.repo_identity.cache_clear()
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
        self.assertRegex(ctx(out), r"## Phase 4|Current phase: 4 .*lines \d+–\d+")

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
        self.assertNotIn("decision", self.stop("Here is the spec.\n[[gate P3]]") or {})
        self.assertEqual(self.e.state()["gate_pending"], 3)
        out = self.e.prompt("approved")
        s = self.e.state()
        self.assertEqual((s["phase"], s["gate_pending"]), (4, None))
        self.assertIn("## Phase 4", ctx(out))
        self.assertIn("approved", ctx(out).lower())

    def test_approval_without_pending_gate_does_nothing(self):
        self.e.prompt("/wf 3")
        self.assertIn("no gate", ctx(self.e.prompt("approved")))
        self.assertEqual(self.e.state()["phase"], 3)

    def test_turn_without_marker_clears_pending_gate(self):
        self.e.prompt("/wf 3")
        self.stop("spec\n[[gate P3]]")
        self.e.prompt("why sqlite?")
        self.stop("Because ... (answer to side question)")
        self.assertIsNone(self.e.state()["gate_pending"])
        self.assertIn("no gate", ctx(self.e.prompt("ok")))
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


# ================================================================ M3: guards

class TestGuardRules(unittest.TestCase):
    def test_flags_merges_into_default_branch(self):
        for cmd, branch in [("git merge feat", "main"), ("cd app && git merge feat", "master"),
                            ("git push origin main", "feat"), ("git push origin HEAD:main", "feat"),
                            ("git push -f origin feat:master", "feat"), ("git push", "main"),
                            ("gh pr merge 3 --squash", "feat")]:
            self.assertTrue(wf.guard_reason(cmd, branch), (cmd, branch))

    def test_allows_normal_work(self):
        for cmd, branch in [("git merge main", "feat"), ("git push -u origin feat", "feat"),
                            ("git status", "main"), ("gh pr create --fill", "feat"),
                            ("git push origin feat-main-fix", "feat"), ("ls", "main")]:
            self.assertFalse(wf.guard_reason(cmd, branch), (cmd, branch))


class TestGuardHook(unittest.TestCase):
    def setUp(self):
        self.e = Env(branch="main")

    def tearDown(self):
        self.e.close()

    def bash(self, cmd):
        return self.e.run("PreToolUse", tool_name="Bash", tool_input={"command": cmd})

    def decision(self, out):
        return out["hookSpecificOutput"]["permissionDecision"] if out else None

    def test_off_and_paused_do_nothing(self):
        self.assertIsNone(self.bash("git merge feat"))
        self.e.prompt("/wf on")
        self.e.prompt("/wf pause")
        self.assertIsNone(self.bash("git merge feat"))

    def test_standard_and_lite_ask(self):
        self.e.prompt("/wf on")
        self.assertEqual(self.decision(self.bash("git merge feat")), "ask")
        self.e.prompt("/wf lite")
        self.assertEqual(self.decision(self.bash("git merge feat")), "ask")
        self.assertIsNone(self.bash("git status"))

    def test_push_to_main_is_guarded_through_the_hook(self):
        self.e.prompt("/wf on strict")
        self.assertEqual(self.decision(self.bash("git push origin refs/heads/main")), "deny")
        self.assertEqual(self.decision(self.bash("git push origin HEAD")), "deny")

    def test_strict_denies_until_phase_10(self):
        self.e.prompt("/wf on strict")
        out = self.bash("git merge feat")
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("/wf", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.e.prompt("/wf 10")
        self.assertEqual(self.decision(self.bash("git merge feat")), "ask")


class TestSubagentAndDuplicates(unittest.TestCase):
    def test_subagent_constraints_only_in_strict(self):
        e = Env()
        try:
            e.prompt("/wf on")
            self.assertIsNone(e.run("SubagentStart", agent_type="general-purpose"))
            e.prompt("/wf strict")
            out = e.run("SubagentStart", agent_type="general-purpose")
            self.assertIn("Global Constraints", ctx(out))
            self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SubagentStart")
        finally:
            e.close()

    def test_warns_about_old_manual_hooks(self):
        e = Env()
        try:
            (e.repo / ".claude").mkdir()
            (e.repo / ".claude" / "settings.json").write_text(
                '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"cat Claude-Workflows-Best-Practices-Compact.md"}]}]}}')
            out = e.prompt("/wf on")
            self.assertIn("twice", ctx(out))
        finally:
            e.close()


# ================================================================ review fixes

class TestReviewFixes(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.close()

    def test_every_injection_fits_hook_limit(self):
        (self.e.repo / "docs/superpowers/specs").mkdir(parents=True)
        (self.e.repo / "docs/superpowers/specs/a-design.md").write_text("s")
        for level in ("lite", "standard", "strict"):
            for n in range(0, 11):
                outs = [self.e.prompt(f"/wf on {level}"), self.e.prompt(f"/wf {n}"),
                        self.e.run("SessionStart", source="compact")]
                for out in outs:
                    self.assertLess(len(ctx(out)), 10000, (level, n))

    def test_oversize_phase_points_to_exact_lines(self):
        self.e.prompt("/wf on")
        out = self.e.prompt("/wf 10")
        text = ctx(out)
        if "## Phase 10" not in text:
            self.assertRegex(text, r"lines \d+–\d+")

    def test_approval_without_gate_gets_a_hint_not_silence(self):
        self.e.prompt("/wf on")
        self.e.prompt("/wf 3")
        out = self.e.prompt("approved")
        self.assertIn("no gate", ctx(out).lower())
        self.assertEqual(self.e.state()["phase"], 3)

    def test_skin_tells_claude_to_repeat_marker_while_waiting(self):
        out = self.e.prompt("/wf on")
        self.assertIn("still waiting", ctx(out))

    def test_approval_word_edge_cases(self):
        for t in ["continue", "great", "good"]:
            self.assertFalse(wf.is_approval(t), t)
        self.assertTrue(wf.is_approval("yes, no changes needed"))
        self.assertTrue(wf.is_approval("looks good, no issues"))

    def test_unicode_digit_is_not_a_phase(self):
        self.assertEqual(wf.parse_command("/wf ²")[0], "²")

    def test_guard_forms(self):
        for cmd, br in [("git push origin HEAD", "main"), ("git push origin +main", "feat"),
                        ("git -C app merge feat", "main"), ("git -c a=b push origin main", "feat"),
                        ("git push --all origin", "feat"), ("git push --mirror origin", "feat"),
                        ("git pull origin feat", "main")]:
            self.assertTrue(wf.guard_reason(cmd, br), (cmd, br))
        for cmd, br in [("git merge-base HEAD main", "main"), ("git pull", "feat"),
                        ("git pull origin main", "main"), ("git push origin HEAD", "feat")]:
            self.assertFalse(wf.guard_reason(cmd, br), (cmd, br))

    def test_completed_feature_is_not_guessed_again(self):
        plan = self.e.repo / "docs/plans/x-plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("p\n## Execution record\n")
        self.e.prompt("/wf on")
        self.e.prompt("/wf 10")
        self.e.run("Stop", last_assistant_message="done\n[[gate P10]]")
        self.e.prompt("approved")
        self.e.prompt("/wf off")
        self.e.prompt("/wf on")
        self.assertIsNone(self.e.state()["phase"])

    def test_state_survives_first_commit_and_detached_heads_differ(self):
        d = Path(self.e.tmp.name) / "fresh"
        subprocess.run(["git", "init", "-q", "-b", "feat", str(d)], check=True)
        wf.handle("UserPromptSubmit", {"prompt": "/wf on", "cwd": str(d)}, self.e.env)
        subprocess.run(["git", "-C", str(d), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "c"], check=True)
        wf.repo_identity.cache_clear()
        self.assertEqual(wf.Store(self.e.env).load(str(d))["enabled"], "on")
        a = wf.repo_identity(str(self.e.repo))
        subprocess.run(["git", "-C", str(self.e.repo), "checkout", "-q", "--detach"], check=True)
        wf.repo_identity.cache_clear()
        self.assertNotEqual(wf.repo_identity(str(self.e.repo))[1], "HEAD")
        self.assertNotEqual(a, wf.repo_identity(str(self.e.repo)))


# ================================================================ F1: visible lines

def shown(out):
    """The line the user sees in the terminal (systemMessage), or ''."""
    return (out or {}).get("systemMessage", "")


class TestVisibleLines(EngineCase):
    def test_wf_commands_show_a_line(self):
        self.assertIn("WF ▸", shown(self.e.prompt("/wf status")))
        self.assertIn("pause", shown(self.e.prompt("/wf pause")).lower())
        self.assertIn("on", shown(self.e.prompt("/wf resume")).lower())
        self.assertIn("off", shown(self.e.prompt("/wf off")).lower())

    def test_gate_reached_and_approved_are_shown(self):
        self.e.prompt("/wf 3")
        out = self.stop("spec\n[[gate P3]]")
        self.assertIn("Gate P3", shown(out))
        out = self.e.prompt("approved")
        self.assertIn("Gate P3 approved → Phase 4", shown(out))

    def test_skill_events_are_shown(self):
        out = self.skill("superpowers:brainstorming")
        self.assertIn("brainstorming", shown(out))
        self.assertIn("Phase 0", shown(out))
        out = self.skill("superpowers:writing-plans")
        self.assertIn("⚠", shown(out))

    def test_shown_text_is_not_sent_to_claude(self):
        self.e.prompt("/wf 3")
        out = self.stop("spec\n[[gate P3]]")
        self.assertNotIn("hookSpecificOutput", out or {})

    def test_turn_without_marker_shows_nothing(self):
        self.assertIsNone(self.stop("just an answer"))

    def test_nothing_shown_when_off(self):
        self.e.prompt("/wf off")
        self.assertIsNone(self.stop("x\n[[gate P3]]"))
        self.assertIsNone(self.skill("superpowers:brainstorming"))


# ================================================================ F2: timeline

class TestTimeline(EngineCase):
    def walk(self, n):
        self.stop(f"x\n[[gate P{n}]]")
        self.e.prompt("approved")

    def marks(self):
        return wf.timeline_marks(self.e.state())

    def test_approved_gates_are_done(self):
        self.e.prompt("/wf new")
        self.walk(0)
        self.walk(1)
        self.assertEqual(self.marks(), "✓✓")
        self.assertEqual(self.e.state()["phase"], 2)

    def test_jumping_ahead_marks_skipped(self):
        self.e.prompt("/wf new")
        self.walk(0)
        self.stop("design doc\n[[gate P3]]")      # Claude jumped from Phase 1 to the P3 gate
        self.assertEqual(self.marks(), "✓⚠⚠")

    def test_skill_jump_marks_skipped(self):
        self.e.prompt("/wf 6")                     # from nothing: no history to mark
        self.e.prompt("/wf 5")                     # loop back
        self.e.prompt("/wf 6")
        self.skill("superpowers:executing-plans")  # 6 → 7 without the P6 gate
        self.assertEqual(wf.timeline_marks(self.e.state())[-1], "⚠")

    def test_loop_back_forgets_later_phases(self):
        self.e.prompt("/wf new")
        for n in range(0, 4):
            self.walk(n)
        self.e.prompt("/wf 2")
        self.assertEqual(self.marks(), "✓✓")

    def test_new_feature_resets_timeline(self):
        self.e.prompt("/wf new")
        self.walk(0)
        self.e.prompt("/wf new")
        self.assertEqual(self.marks(), "")

    def test_status_shows_timeline(self):
        self.e.prompt("/wf new")
        self.walk(0)
        self.stop("x\n[[gate P2]]")
        out = self.e.prompt("/wf status")
        self.assertRegex(shown(out), r"P0 ✓( \d+%)? · P1 ⚠ skipped · P2")

    def test_statusline_shows_marks(self):
        self.e.prompt("/wf new")
        self.walk(0)
        self.walk(1)
        self.assertEqual(wf.statusline({"cwd": str(self.e.repo)}, self.e.env), "[WF P2 · ✓✓ · standard]")


# ================================================================ F3: checklist %

FULL_SPEC = """Behavior: subtract returns a-b. Interfaces: subtract(a, b) -> number. Edge cases: negatives,
floats. Transactional integrity: N/A, no writes. Assumptions: callers pass numbers. Access-control
matrix: no access boundaries. Expected scale: N/A, pure function. Reuse: follows add(). Presentation vs
logic: N/A. Checkpoint: no conflicts with existing code, no unverified assumptions."""


def checklist(n, skip=(), bad=None):
    """A gate message whose checklist covers every item of phase n except `skip`."""
    lines = []
    for label, _ in wf.CHECKS[n]:
        if label in skip:
            continue
        lines.append(f"- {label}: {bad if bad and label == bad[0] else 'covered in section 1'}"
                     if not isinstance(bad, tuple) else
                     f"- {label}: {bad[1] if label == bad[0] else 'covered in section 1'}")
    return "Gate summary\n" + "\n".join(lines) + f"\n\n[[gate P{n}]]"


class TestChecklist(EngineCase):
    def test_every_phase_has_a_checklist_with_unique_labels(self):
        for n in range(0, 11):
            labels = [l for l, _ in wf.CHECKS[n]]
            self.assertGreaterEqual(len(labels), 3, n)
            self.assertEqual(len(labels), len(set(labels)), n)

    def test_full_checklist_scores_100(self):
        r = wf.score(1, checklist(1))
        self.assertEqual((r["found"], r["missing"], r["unverified"]), (r["total"], [], []))

    def test_mentioning_items_as_left_out_scores_zero(self):
        msg = ("I left out edge cases, transactional integrity, assumptions, access control, scale, "
               "reuse, and presentation vs logic.\n[[gate P3]]")
        self.assertEqual(wf.score(3, msg)["found"], 0)

    def test_negative_answers_do_not_count(self):
        for val in ("missing", "TODO", "TBD", "not covered yet", "left out", "?", "skipped",
                    "**not covered** (left out)", "**partially done**, only opened calc.py", "partial"):
            r = wf.score(1, checklist(1, bad=("constraints", val)))
            self.assertIn("constraints", r["missing"], val)

    def test_na_with_reason_counts(self):
        r = wf.score(1, checklist(1, bad=("constraints", "N/A — greenfield, none")))
        self.assertEqual(r["missing"], [])

    def test_claim_not_found_in_spec_file_is_unverified(self):
        d = self.e.repo / "docs/superpowers/specs"
        d.mkdir(parents=True)
        (d / "s-design.md").write_text(FULL_SPEC.replace("Access-control\nmatrix: no access boundaries.", ""))
        r = wf.score(3, checklist(3), wf.phase_file(3, str(self.e.repo)))
        self.assertEqual(r["unverified"], ["access-control matrix"])
        self.assertEqual(r["found"], r["total"] - 1)

    def test_gate_line_shows_score_missing_and_unverified(self):
        self.e.prompt("/wf 3")
        out = self.stop(checklist(3, skip=("expected scale",)))
        self.assertRegex(shown(out), r"Gate P3 reached · checklist \d+/\d+ \(\d+%\) · missing: expected scale")

    def test_no_checklist_block_says_so(self):
        self.e.prompt("/wf 3")
        self.assertIn("no checklist lines", shown(self.stop("Here is the spec.\n[[gate P3]]")))

    def test_phase_rules_tell_claude_the_checklist_labels(self):
        out = self.e.prompt("/wf 2")
        for label, _ in wf.CHECKS[2]:
            self.assertIn(label, ctx(out))

    def test_score_reaches_statusline_and_timeline(self):
        self.e.prompt("/wf 3")
        self.stop(checklist(3, skip=("reuse", "assumptions")))
        pct = wf.score_pct(self.e.state()["timeline"]["3"])
        self.assertEqual(pct, 80)
        self.assertRegex(wf.statusline({"cwd": str(self.e.repo)}, self.e.env), r"\[WF P3 80%")
        self.e.prompt("approved")
        self.assertIn("P3 ✓ 80%", shown(self.e.prompt("/wf status")))


# ================================================================ F4: strict nudge

class TestStrictNudge(EngineCase):
    def gate3(self, msg="Behavior: x. Interfaces: y.\n[[gate P3]]", active=False):
        return self.e.run("Stop", last_assistant_message=msg, stop_hook_active=active)

    def test_strict_blocks_once_with_missing_list(self):
        self.e.prompt("/wf strict")
        self.e.prompt("/wf 3")
        out = self.gate3()
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("access-control matrix", out["reason"])
        self.assertIn("N/A", out["reason"])
        self.assertIn("[[gate P3]]", out["reason"])
        self.assertIn("missing", shown(out))
        again = self.gate3()                       # Claude ends at the gate again, still incomplete
        self.assertNotIn("decision", again)
        self.assertIn("missing", shown(again))

    def test_respects_stop_hook_active(self):
        self.e.prompt("/wf strict")
        self.e.prompt("/wf 3")
        self.assertNotIn("decision", self.gate3(active=True))

    def test_standard_never_blocks(self):
        self.e.prompt("/wf 3")
        self.assertNotIn("decision", self.gate3())

    def test_complete_gate_not_blocked(self):
        self.e.prompt("/wf strict")
        self.e.prompt("/wf 3")
        self.assertNotIn("decision", self.gate3(checklist(3)))

    def test_loop_back_allows_a_new_nudge(self):
        self.e.prompt("/wf strict")
        self.e.prompt("/wf 3")
        self.gate3()
        self.e.prompt("approved")
        self.e.prompt("/wf 3")
        self.assertEqual(self.gate3().get("decision"), "block")


class TestReview2Fixes(EngineCase):
    def test_finished_feature_timeline_does_not_leak(self):
        self.e.prompt("/wf strict")
        self.e.prompt("/wf 10")
        self.stop("deployed\n[[gate P10]]")
        self.e.prompt("approved")
        self.e.prompt("/wf 0")
        self.assertEqual(self.e.state()["timeline"], {})

    def test_reemitting_gate_without_lines_keeps_score(self):
        self.e.prompt("/wf 1")
        self.stop(checklist(1))
        self.stop("Answer to your side question.\n[[gate P1]]")
        self.assertEqual(wf.score_pct(self.e.state()["timeline"]["1"]), 100)

    def test_old_feature_spec_is_not_used(self):
        d = self.e.repo / "docs/superpowers/specs"
        d.mkdir(parents=True)
        old = d / "old-design.md"
        old.write_text(FULL_SPEC)
        os.utime(old, (1, 1))
        self.e.prompt("/wf new")
        self.assertIsNone(wf.phase_file(3, str(self.e.repo), self.e.state()))

    def test_only_spec_plan_phases_check_files(self):
        self.assertIsNone(wf.phase_file(8, str(self.e.repo), self.e.state()))

    def test_strict_does_not_block_a_question(self):
        self.e.prompt("/wf strict")
        self.e.prompt("/wf 0")
        out = self.stop("Is this Full or Quick tier?\n\n[[gate P0]]")
        self.assertNotIn("decision", out)


# ================================================================ review R3/R4: cheap when off

from unittest import mock  # noqa: E402


class TestCheapWhenOff(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        wf.repo_identity.cache_clear()

    def tearDown(self):
        self.e.close()

    def bash(self):
        return self.e.run("PreToolUse", tool_name="Bash", tool_input={"command": "git merge x"})

    def git_calls(self, fn):
        real = subprocess.run
        calls = []
        def spy(cmd, *a, **k):
            if cmd and cmd[0] == "git":
                calls.append(cmd)
            return real(cmd, *a, **k)
        with mock.patch.object(wf.subprocess, "run", side_effect=spy):
            fn()
        return calls

    def test_never_used_creates_no_files(self):
        self.bash()
        self.e.run("Stop", last_assistant_message="x\n[[gate P3]]")
        self.e.prompt("hello")
        self.assertFalse((self.e.data / "state").exists())

    def test_never_used_runs_at_most_two_git_commands(self):
        self.assertEqual(len(self.git_calls(self.bash)), 0)        # nothing on this machine yet
        other = Env()
        try:
            other.prompt("/wf on")                                   # the skin is used in another repo
            self.e.env["CLAUDE_PLUGIN_DATA"] = other.env["CLAUDE_PLUGIN_DATA"]
            self.assertLessEqual(len(self.git_calls(self.bash)), 2)
        finally:
            other.close()

    def test_switched_off_takes_no_lock(self):
        self.e.prompt("/wf on")
        self.e.prompt("/wf off")
        for f in (self.e.data / "state").glob("*.lock"):
            f.unlink()
        self.bash()
        self.assertEqual(list((self.e.data / "state").glob("*.lock")), [])

    def test_wf_command_still_works_from_nothing(self):
        self.e.prompt("/wf on")
        self.assertEqual(self.e.state()["enabled"], "on")


class TestStatuslineSnippetQuoting(unittest.TestCase):
    def test_snippet_command_runs_with_space_in_path(self):
        e = Env()
        try:
            e.env["CLAUDE_PLUGIN_DATA"] = str(Path(e.tmp.name) / "my data")
            e.prompt("/wf on")
            text = ctx(e.prompt("/wf statusline"))
            snippet = json.loads("{" + re.search(r'("statusLine": \{.*?\})', text).group(1) + "}")
            cmd = snippet["statusLine"]["command"]
            p = subprocess.run(cmd, shell=True, input=json.dumps({"workspace": {"current_dir": str(e.repo)}}),
                               capture_output=True, text=True)
            self.assertEqual((p.returncode, p.stdout), (0, "[WF P– · standard]"), p.stderr)
        finally:
            e.close()


# ================================================================ review S4/S6

class TestMissingDocs(unittest.TestCase):
    def test_no_doc_anywhere_says_rules_file_not_found(self):
        e = Env()
        try:
            empty = Path(e.tmp.name) / "empty-plugin"
            empty.mkdir()
            e.env["CLAUDE_PLUGIN_ROOT"] = str(empty)
            e.prompt("/wf on")
            text = ctx(e.prompt("/wf 4"))
            self.assertNotIn("None", text)
            self.assertIn("rules file not found", text)
            self.assertIn("ownership map", text)          # the checklist still arrives
            self.assertIn("rules file not found", ctx(e.prompt("/wf lite")))
        finally:
            e.close()


class TestEarlierGateIsARecap(EngineCase):
    def test_earlier_gate_does_not_erase_timeline_or_move_back(self):
        self.e.prompt("/wf new")
        for n in range(0, 6):
            self.stop(f"x\n[[gate P{n}]]")
            self.e.prompt("approved")
        before = dict(self.e.state()["timeline"])
        out = self.stop("Recap of the plan.\n[[gate P4]]")
        s = self.e.state()
        self.assertEqual(s["phase"], 6)
        self.assertEqual(s["timeline"], before)
        self.assertIsNone(s["gate_pending"])
        self.assertIn("/wf 4", shown(out))

    def test_skin_tells_claude_loop_backs_are_the_users_call(self):
        self.assertIn("`/wf <n>`", ctx(self.e.prompt("/wf 5")))

    def test_loop_back_still_works_with_wf_n(self):
        self.e.prompt("/wf new")
        for n in range(0, 6):
            self.stop(f"x\n[[gate P{n}]]")
            self.e.prompt("approved")
        self.e.prompt("/wf 3")
        self.assertEqual(self.e.state()["phase"], 3)
        self.assertEqual(wf.timeline_marks(self.e.state()), "✓✓✓")


# ================================================================ consistency review C1: follow branch switches

def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class TestFollowBranch(unittest.TestCase):
    def setUp(self):
        self.e = Env(branch="main")
        self.e.prompt("/wf on")
        self.e.prompt("/wf 6")

    def tearDown(self):
        self.e.close()

    def test_new_feature_branch_follows(self):
        git(self.e.repo, "checkout", "-q", "-b", "feat-x")
        out = self.e.run("PreToolUse", tool_name="Bash", tool_input={"command": "ls"})
        s = self.e.state()
        self.assertEqual((s["enabled"], s["phase"]), ("on", 6))
        self.assertIn("main → feat-x", shown(out))

    def test_worktree_follows_and_gate_works_there(self):
        wt = Path(self.e.tmp.name) / "wt"
        git(self.e.repo, "worktree", "add", "-q", "-b", "feat-y", str(wt))
        out = wf.handle("Stop", {"cwd": str(wt), "last_assistant_message": "x\n[[gate P6]]"}, self.e.env)
        self.assertIn("Gate P6", shown(out))
        wf.repo_identity.cache_clear()
        self.assertEqual(wf.Store(self.e.env).load(str(wt))["gate_pending"], 6)

    def test_back_on_main_is_the_same_feature_and_still_guarded(self):
        git(self.e.repo, "checkout", "-q", "-b", "feat-x")
        self.e.prompt("/wf 8")
        git(self.e.repo, "checkout", "-q", "main")
        self.assertEqual(self.e.state()["phase"], 8)
        out = self.e.run("PreToolUse", tool_name="Bash", tool_input={"command": "git merge feat-x"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_wf_new_on_followed_branch_starts_separate_feature(self):
        git(self.e.repo, "checkout", "-q", "-b", "feat-x")
        self.e.prompt("/wf new")
        self.assertEqual(self.e.state()["phase"], 0)
        git(self.e.repo, "checkout", "-q", "main")
        self.assertEqual(self.e.state()["phase"], 6)          # the original feature is back on main

    def test_off_skin_is_not_followed(self):
        self.e.prompt("/wf off")
        git(self.e.repo, "checkout", "-q", "-b", "feat-x")
        self.assertIsNone(self.e.run("PreToolUse", tool_name="Bash", tool_input={"command": "ls"}))
        self.assertEqual(self.e.state()["enabled"], "off")


class TestStartPhase(EngineCase):
    def test_start_phase_7_approves_the_p6_gate(self):
        self.e.prompt("/wf 6")
        self.stop("TDD plan\n[[gate P6]]")
        out = self.e.prompt("start Phase 7")
        self.assertEqual(self.e.state()["phase"], 7)
        self.assertIn("Gate P6 approved → Phase 7", shown(out))

    def test_start_phase_must_be_the_next_phase(self):
        self.e.prompt("/wf 3")
        self.stop("spec\n[[gate P3]]")
        out = self.e.prompt("start phase 5")
        self.assertEqual(self.e.state()["phase"], 3)
        self.assertIn("Phase 4", ctx(out))

    def test_docs_say_p6_approval_is_the_go(self):
        doc = (ROOT / "Claude-Workflows-Best-Practices.md").read_text()
        self.assertNotIn('execution starts only when I say "start Phase 7"', doc)
        self.assertIn("approving the Phase 6 gate", doc)


class TestGuardSequences(unittest.TestCase):
    def test_switch_to_default_inside_one_command(self):
        for cmd in ["git checkout main && git pull && git merge feat",
                    "git switch master; git merge feat",
                    "cd /repo && git checkout main\ngit merge --no-ff feat",
                    "git checkout main && git pull origin feat"]:
            self.assertTrue(wf.guard_reason(cmd, "feat"), cmd)

    def test_commit_on_default_branch(self):
        self.assertTrue(wf.guard_reason("git add docs && git commit -m spec", "main"))
        self.assertTrue(wf.guard_reason("git checkout main && git commit -am x", "feat"))
        self.assertIn("commit", wf.guard_reason("git commit -m x", "master"))

    def test_still_allowed(self):
        for cmd, br in [("git checkout -b feat && git commit -m x", "main"),
                        ("git switch -c feat; git commit -m x", "main"),
                        ("git checkout main -- README.md && git commit -m restore", "feat"),
                        ("git commit -m x", "feat"),
                        ("git checkout main && git log", "feat"),
                        ("git checkout main && git checkout -b fix && git merge feat", "feat")]:
            self.assertFalse(wf.guard_reason(cmd, br), (cmd, br))


# ================================================================ C4/C5: checklists come from the doc

SP_PLAN = """# Subtract Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
**Goal:** add subtract
## Global Constraints
- access-control matrix: none
## Ownership map
- subtract lives in calc.py
---
### Task 1: subtract
- [ ] **Step 1: Write the failing test** `[Sad]`
- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_calc.py -v`
Expected: FAIL
"""


class TestChecklistFromDoc(unittest.TestCase):
    def test_labels_are_read_from_the_doc(self):
        doc = (ROOT / "Claude-Workflows-Best-Practices.md").read_text()
        for n in range(0, 11):
            items = wf.checks_from_doc(doc, n)
            self.assertEqual([l for l, _ in items], [l for l, _ in wf.CHECKS[n]], n)
            self.assertGreaterEqual(len(items), 3, n)

    def test_every_file_item_has_a_pattern(self):
        for n, items in wf.CHECKS.items():
            for label, is_file in items:
                if is_file:
                    self.assertIn(label, wf.FILE_PATTERNS, (n, label))

    def test_project_doc_labels_win(self):
        e = Env()
        try:
            (e.repo / "Claude-Workflows-Best-Practices.md").write_text(
                "## Phase 4 — Plan\nrules\n\n**Gate checklist:** team sign-off · risk log\n\n---\n")
            e.prompt("/wf on")
            text = ctx(e.prompt("/wf 4"))
            self.assertIn("team sign-off; risk log", text)
        finally:
            e.close()

    def test_superpowers_plan_format_only_flags_real_file_gaps(self):
        r = wf.score(4, checklist(4), SP_PLAN)
        self.assertEqual(r["unverified"], ["exit state per step"])   # the doc requires it; writing-plans doesn't add it

    def test_chat_items_are_never_checked_against_files(self):
        r = wf.score(6, checklist(6), SP_PLAN)
        self.assertEqual(r["unverified"], [])
        r = wf.score(3, checklist(3), FULL_SPEC.replace("Checkpoint: no conflicts with existing code, no unverified assumptions.", ""))
        self.assertEqual(r["unverified"], [])


class TestFilesFromWorktreeAndCustomDirs(unittest.TestCase):
    def setUp(self):
        self.e = Env(branch="main")
        (self.e.repo / ".gitignore").write_text("docs/\n")
        git(self.e.repo, "add", ".gitignore")
        git(self.e.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "ignore docs")
        self.e.prompt("/wf on")

    def tearDown(self):
        self.e.close()

    def test_worktree_finds_gitignored_spec_and_plan_in_main_checkout(self):
        d = self.e.repo / "docs/superpowers/plans"
        d.mkdir(parents=True)
        (d / "2026-11-01-x.md").write_text(SP_PLAN)
        wt = Path(self.e.tmp.name) / "wt"
        git(self.e.repo, "worktree", "add", "-q", "-b", "feat", str(wt))
        wf.repo_identity.cache_clear()
        self.assertIn("Ownership map", wf.phase_file(4, str(wt), {}) or "")
        self.assertEqual(wf.guess_phase(str(wt))[0], 5)

    def test_dirs_keep_their_case(self):
        self.assertEqual(wf.parse_command("/wf dirs Design/Specs Design/Plans"),
                         ("dirs", ["Design/Specs", "Design/Plans"]))

    def test_custom_dirs(self):
        out = self.e.prompt("/wf dirs design/specs design/plans")
        self.assertIn("design/specs", shown(out) + ctx(out))
        d = self.e.repo / "design/plans"
        d.mkdir(parents=True)
        (d / "p.md").write_text(SP_PLAN)
        wf.repo_identity.cache_clear()
        self.assertIn("Ownership map", wf.phase_file(4, str(self.e.repo), self.e.state()) or "")
        self.assertEqual(wf.guess_phase(str(self.e.repo), 0, self.e.state().get("dirs"))[0], 5)


class TestCombinedFirstMessage(EngineCase):
    def first_message(self, with_p0=True):
        p0 = checklist(0).rsplit("\n\n", 1)[0] if with_p0 else ""
        p1 = checklist(1).rsplit("\n\n", 1)[0]
        return "Here is what I understand...\n" + p0 + "\n" + p1 + "\n\n[[gate P1]]"

    def test_p0_lines_in_p1_gate_count_for_p0(self):
        self.skill("superpowers:brainstorming")
        self.stop(self.first_message())
        self.e.prompt("approved")
        self.assertEqual(wf.timeline_marks(self.e.state()), "✓✓")

    def test_without_p0_lines_p0_is_skipped(self):
        self.skill("superpowers:brainstorming")
        self.stop(self.first_message(with_p0=False))
        self.e.prompt("approved")
        self.assertEqual(wf.timeline_marks(self.e.state()), "⚠✓")

    def test_brainstorming_note_allows_one_combined_gate(self):
        out = self.skill("superpowers:brainstorming")
        self.assertIn("[[gate P1]]", ctx(out))
        self.assertIn("Phase 0", ctx(out))


class TestSkillFile(unittest.TestCase):
    def test_wf_skill_is_user_only(self):
        front = (ROOT / "skills/wf/SKILL.md").read_text().split("---")[1]
        self.assertIn("disable-model-invocation: true", front)


class TestExecutorReminderMatchesDocs(EngineCase):
    def test_lists_every_ledger_line_the_docs_require(self):
        self.e.prompt("/wf 6")
        text = ctx(self.skill("superpowers:executing-plans"))
        for item in ("Ruling", "parked", "minor (deferred)", "no reachable spec"):
            self.assertIn(item, text)
        doc = (ROOT / "Claude-Workflows-Best-Practices.md").read_text()
        self.assertIn('"no reachable spec"', doc)


# ================================================================ /wf help

class TestHelp(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.close()

    def test_help_shows_everyday_guide_in_terminal(self):
        out = self.e.prompt("/wf help")
        text = shown(out)
        for cmd in ("/wf on", "/wf pause", "/wf status", "/wf off", "approved", "/wf help strict"):
            self.assertIn(cmd, text)
        self.assertNotIn(text.splitlines()[1], ctx(out))   # the guide is shown, not sent to Claude

    def test_help_changes_nothing_and_creates_no_state(self):
        self.e.prompt("/wf help")
        self.assertFalse((self.e.data / "state").exists())

    def test_every_command_has_a_topic_with_an_example(self):
        for topic in ("on", "off", "pause", "resume", "status", "lite", "standard", "strict", "new",
                      "phase", "dirs", "default", "statusline", "gate", "levels"):
            text = shown(self.e.prompt(f"/wf help {topic}"))
            self.assertIn("Example", text, topic)
            self.assertLess(len(text.splitlines()), 9, topic)

    def test_help_number_means_phase_topic(self):
        self.assertIn("go back", shown(self.e.prompt("/wf help 4")).lower())

    def test_unknown_command_shows_help_in_terminal(self):
        out = self.e.prompt("/wf banana")
        self.assertIn("unknown", shown(out).lower())
        self.assertIn("/wf help", shown(out))

    def test_unknown_topic(self):
        self.assertIn("/wf help", shown(self.e.prompt("/wf help xyz")))


class TestShortHint(unittest.TestCase):
    def test_hint_is_short(self):
        front = (ROOT / "skills/wf/SKILL.md").read_text().split("---")[1]
        hint = re.search(r'argument-hint:\s*"(.*)"', front).group(1)
        self.assertEqual(hint, "[on | off | pause | status | help]")

    def test_plugin_version_matches_readme(self):
        version = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
        self.assertIn(f"**Version:** v{version}", (ROOT / "README.md").read_text())
