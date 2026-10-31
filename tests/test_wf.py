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
        self.assertEqual(wf.Store(self.e.env).load(str(d))["enabled"], "on")
        a = wf.repo_identity(str(self.e.repo))
        subprocess.run(["git", "-C", str(self.e.repo), "checkout", "-q", "--detach"], check=True)
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


class TestChecklist(EngineCase):
    def test_every_phase_has_a_checklist(self):
        for n in range(0, 11):
            self.assertGreaterEqual(len(wf.CHECKS[n]), 3, n)

    def test_full_spec_scores_100(self):
        found, total, missing = wf.score(3, FULL_SPEC)
        self.assertEqual((found, missing), (total, []))

    def test_missing_items_are_named(self):
        text = FULL_SPEC.replace("Access-control\nmatrix: no access boundaries.", "").replace(
            "Expected scale: N/A, pure function.", "")
        found, total, missing = wf.score(3, text)
        self.assertEqual(found, total - 2)
        self.assertEqual(missing, ["access-control matrix", "expected scale"])

    def test_gate_shows_score_and_missing(self):
        self.e.prompt("/wf 3")
        out = self.stop("Spec:\nBehavior: x. Interfaces: y. Edge cases: z.\n[[gate P3]]")
        line = shown(out)
        self.assertRegex(line, r"Gate P3 reached · checklist \d+/\d+ \(\d+%\) · missing: ")
        self.assertIn("access-control matrix", line)

    def test_spec_file_counts_for_phase_3(self):
        d = self.e.repo / "docs/superpowers/specs"
        d.mkdir(parents=True)
        (d / "2026-11-01-sub-design.md").write_text(FULL_SPEC)
        self.e.prompt("/wf 3")
        out = self.stop("The spec is saved; please review.\n[[gate P3]]")
        self.assertIn("all items ✓", shown(out))

    def test_plan_file_counts_for_phase_4(self):
        d = self.e.repo / "docs/superpowers/plans"
        d.mkdir(parents=True)
        (d / "plan.md").write_text("## Global Constraints\n... Ownership map ...\n")
        self.e.prompt("/wf 4")
        out = self.stop("Plan saved.\n[[gate P4]]")
        self.assertNotIn("global constraints", shown(out).split("missing:")[-1])

    def test_score_reaches_statusline_and_timeline(self):
        self.e.prompt("/wf new")
        self.stop("x\n[[gate P0]]")
        self.e.prompt("approved")
        self.e.prompt("/wf 3")
        self.stop("Behavior: x. Interfaces: y.\n[[gate P3]]")
        pct = wf.score_pct(self.e.state()["timeline"]["3"])
        self.assertRegex(wf.statusline({"cwd": str(self.e.repo)}, self.e.env), rf"\[WF P3 {pct}% · ")
        self.e.prompt("approved")
        self.assertIn(f"P3 ✓ {pct}%", shown(self.e.prompt("/wf status")))
