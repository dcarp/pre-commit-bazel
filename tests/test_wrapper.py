import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from support import checked, commit, copy_plugin, init_git, install_fake_bazel, run


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bazel-python-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plugin = self.root / "plugin 'copy'"
        copy_plugin(self.plugin)
        self.workspace = self.root / "work space"
        self.workspace.mkdir()
        init_git(self.workspace)
        (self.workspace / "MODULE.bazel").touch()
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(self.plugin / "src")
        self.env["BAZEL_TEST_LOG"] = str(self.root / "builds.log")
        tool = self.root / "probe.py"
        tool.write_text(
            "import json, os, sys\n"
            "print(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n"
            "print('Tool stderr', file=sys.stderr)\n"
            "sys.exit(int(os.environ.get('TOOL_TEST_STATUS', '0')))\n"
        )
        self.env["BAZEL_TEST_TOOL"] = str(tool)
        install_fake_bazel(self.root / "bin", self.env)
        self.interpreter = sys.executable

    def invoke(self, *arguments, status=0):
        result = run(
            [self.interpreter, "-m", "pre_commit_bazel", *arguments],
            cwd=self.workspace,
            env=self.env,
        )
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return result

    def builds(self):
        log = Path(self.env["BAZEL_TEST_LOG"])
        return (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )

    def test_arguments_cwd_and_streams(self):
        args = [
            "file with spaces.txt",
            "",
            "$(touch unexpected)",
            "*.txt",
            "--",
            "--flag=value",
            "quote'\"\n",
        ]
        result = self.invoke("--", "//:probe", *args)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "cwd": str(self.workspace.resolve()),
                "args": ["--from-target", *args],
            },
        )
        self.assertIn("Built launcher", result.stderr)
        self.assertIn("Tool stderr", result.stderr)
        self.assertFalse((self.workspace / "unexpected").exists())
        self.assertEqual(self.builds(), ["//:probe"])

    def test_reuse_and_exit_status_without_retry(self):
        self.invoke("--", "//:probe", "old")
        self.env["BAZEL_TEST_FAILURE"] = "91"
        result = self.invoke("--", "//:probe", "new")
        self.assertEqual(json.loads(result.stdout)["args"], ["--from-target", "new"])
        self.env["TOOL_TEST_STATUS"] = "17"
        self.invoke("--", "//:probe", status=17)
        self.assertEqual(self.builds(), ["//:probe"])

    def test_refresh_and_failed_refresh_recovery(self):
        self.invoke("--", "//:probe")
        self.env["BAZEL_TEST_FAILURE"] = "91"
        self.invoke("--refresh", "--", "//:probe", status=91)
        self.invoke("--", "//:probe")
        self.assertFalse(
            list((self.workspace / ".git/pre-commit-bazel/v2").glob(".launcher.*"))
        )
        del self.env["BAZEL_TEST_FAILURE"]
        self.invoke("--refresh", "--", "//:probe")
        self.assertEqual(len(self.builds()), 3)

    def test_separate_targets(self):
        labels = [
            "//tools:other",
            "@tools//:probe",
            "@@tools+//:probe",
            "//:bazel_env/tools/probe",
        ]
        for label in labels:
            self.invoke("--", label)
            self.invoke("--", label)
        self.assertEqual(self.builds(), labels)

    def test_invalid_input(self):
        for label in [
            "--flag",
            "probe",
            "//tools",
            "//...",
            "//tools:all",
            "//tools:all-targets",
            "//tools:*",
            "//tools:?",
            "//:one //:two",
        ]:
            with self.subTest(label=label):
                self.invoke("--", label, status=2)
        for args in [[], ["--"], ["--refresh"], ["--ref"], ["--unknown"], ["//:probe"]]:
            with self.subTest(args=args):
                self.invoke(*args, status=2)
        self.assertIn("usage:", self.invoke("--help").stdout)
        self.assertFalse(self.builds())

    def test_incomplete_launcher_is_not_cached(self):
        self.env["BAZEL_TEST_NO_OUTPUT"] = "1"
        result = self.invoke("--", "//:probe", status=2)
        self.assertIn("did not generate an executable launcher", result.stderr)
        self.assertEqual(
            list((self.workspace / ".git/pre-commit-bazel/v2").iterdir()), []
        )

    def test_warm_cache_without_bazel(self):
        self.invoke("--", "//:probe")
        git_bin = self.root / "git-only"
        git_bin.mkdir()
        (git_bin / "git").symlink_to(shutil.which("git"))
        # Bazel emits /bin/bash, and Python helper paths are absolute.
        self.env["PATH"] = str(git_bin)
        self.invoke("--", "//:probe")
        result = self.invoke("--", "//:missing", status=2)
        self.assertIn("bazel is required on PATH", result.stderr)

    def test_worktree_cache_is_separate(self):
        self.invoke("--", "//:probe")
        commit(self.workspace)
        worktree = self.root / "second worktree"
        checked(
            ["git", "worktree", "add", "-q", "-b", "other", str(worktree)],
            cwd=self.workspace,
        )
        self.workspace = worktree
        self.invoke("--", "//:probe")
        self.assertEqual(len(self.builds()), 2)

    def test_package_and_interpreter_paths(self):
        self.invoke("--", "//:probe")
        interpreter = self.root / "python 'with spaces'"
        interpreter.symlink_to(sys.executable)
        self.interpreter = str(interpreter)
        self.invoke("--", "//:probe", "different interpreter")
        other_plugin = self.root / "other plugin"
        copy_plugin(other_plugin)
        self.env["PYTHONPATH"] = str(other_plugin / "src")
        self.invoke("--", "//:probe")
        self.assertEqual(len(self.builds()), 3)

    def test_workspace_errors(self):
        (self.workspace / "MODULE.bazel").unlink()
        self.assertIn(
            "MODULE.bazel is missing", self.invoke("--", "//:probe", status=2).stderr
        )
        nested = self.workspace / "nested"
        nested.mkdir()
        (nested / "MODULE.bazel").touch()
        self.workspace = nested
        self.assertIn(
            "Git repository root", self.invoke("--", "//:probe", status=2).stderr
        )
        self.workspace = self.root / "not a repository"
        self.workspace.mkdir()
        (self.workspace / "MODULE.bazel").touch()
        self.assertIn(
            "Git working tree", self.invoke("--", "//:probe", status=2).stderr
        )
        self.env["PATH"] = ""
        self.assertIn(
            "git is required on PATH", self.invoke("--", "//:probe", status=2).stderr
        )

    def test_missing_artifact_failure_requires_explicit_refresh(self):
        self.invoke("--", "//:probe")
        Path(self.env["BAZEL_TEST_TOOL"]).unlink()
        result = self.invoke("--", "//:probe", status=2)
        self.assertIn("can't open file", result.stderr)
        self.assertEqual(len(self.builds()), 1)

    def test_old_cache_is_left_untouched(self):
        old_cache = self.workspace / ".git/pre-commit-bazel/v1"
        old_cache.mkdir(parents=True)
        sentinel = old_cache / "old-launcher"
        sentinel.write_text("old")
        self.invoke("--", "//:probe")
        self.assertEqual(sentinel.read_text(), "old")
