import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HarnessTests(unittest.TestCase):
    def run_checks(self, folder, checks):
        config = folder / "checks.json"
        config.write_text(json.dumps({"checks": checks}), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/checks.py"), "--config", str(config),
             "--root", str(folder), "--output", str(folder / "runs")],
            capture_output=True, text=True, timeout=15)
        reports = sorted((folder / "runs").glob("*/report.json"))
        report = json.loads(reports[-1].read_text()) if reports else None
        return result, report

    def test_pass_failure_and_literal_shell_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            result, report = self.run_checks(path, [
                {"name": "literal", "argv": ["{python}", "-c", "import sys; print(sys.argv[1])", "$(touch unwanted)"],
                 "stdout_contains": ["$(touch unwanted)"]},
                {"name": "bad", "argv": ["{python}", "-c", "raise SystemExit(7)"]},
                {"name": "expected-error", "argv": ["{python}", "-c", "raise SystemExit(3)"], "expect_exit": 3}])
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual([x["passed"] for x in report["results"]], [True, False, True])
            self.assertFalse((path / "unwanted").exists())
            self.assertTrue(report["complete"])

    def test_timeout_missing_command_and_missing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, report = self.run_checks(Path(tmp), [
                {"name": "timeout", "argv": ["{python}", "-c", "import time; time.sleep(10)"], "timeout": 0.1},
                {"name": "missing", "argv": [str(Path(tmp) / "missing-command")]},
                {"name": "output", "argv": ["{python}", "-c", "print('actual')"], "stdout_contains": ["expected"]}])
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(report["results"][0]["timeout"])
            self.assertIsNotNone(report["results"][1]["error"])
            self.assertEqual(report["results"][2]["missing_stdout"], ["expected"])

    def test_invalid_config_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            result, report = self.run_checks(path, [
                {"name": "valid", "argv": ["{python}", "-c", "open('unwanted', 'w').close()"]},
                {"name": "invalid", "argv": "echo invalid"}])
            self.assertEqual(result.returncode, 2)
            self.assertIsNone(report)
            self.assertFalse((path / "unwanted").exists())

    def test_separate_runs_preserve_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            check = [{"name": "success", "argv": ["{python}", "-c", "print('ok')"]}]
            for _ in range(2):
                result, _ = self.run_checks(path, check)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list((path / "runs").glob("*/report.json"))), 2)


class InstallerTests(unittest.TestCase):
    def prepare(self, target):
        kit = target / ".hackkit"
        shutil.copytree(ROOT / "skills", kit / "skills")
        (kit / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/install.py", kit / "scripts/install.py")
        for filename in ("AGENTS.md", "CONTEXT.md"):
            shutil.copyfile(ROOT / filename, kit / filename)
        return kit

    def install(self, kit, target):
        return subprocess.run([sys.executable, str(kit / "scripts/install.py"), "--target", str(target)],
                              capture_output=True, text=True, timeout=10)

    def test_preserves_instructions_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            kit = self.prepare(target)
            (target / "AGENTS.md").write_text("# Existing\nKeep me.\n", encoding="utf-8")
            (target / ".gitignore").write_text("existing/\n", encoding="utf-8")
            result = self.install(kit, target)
            self.assertEqual(result.returncode, 0, result.stderr)
            before = {p: (target / p).read_bytes() for p in ("AGENTS.md", ".gitignore")}
            result = self.install(kit, target)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, {p: (target / p).read_bytes() for p in before})
            self.assertTrue((target / "AGENTS.md").read_text().startswith("# Existing\nKeep me.\n"))
            self.assertEqual(len(list((target / ".agents/skills").glob("*/SKILL.md"))), 6)

    def test_conflict_does_not_partially_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            kit = self.prepare(target)
            existing = target / ".agents/skills/verify-deliver/SKILL.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("User's existing skill", encoding="utf-8")
            result = self.install(kit, target)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(existing.read_text(), "User's existing skill")
            self.assertFalse((target / "AGENTS.md").exists())
            self.assertEqual(len(list((target / ".agents/skills").glob("*/SKILL.md"))), 1)


if __name__ == "__main__":
    unittest.main()
