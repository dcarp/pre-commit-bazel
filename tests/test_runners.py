import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from support import ROOT, checked, commit, copy_plugin, init_git, install_fake_bazel


class RunnerTests(unittest.TestCase):
    def exercise(self, real):
        for runner in ("pre-commit", "prek"):
            if shutil.which(runner) is None:
                self.skipTest(f"{runner} is required for runner integration tests")
        temporary = tempfile.TemporaryDirectory(prefix="bazel-runner-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        plugin = root / "plugin 'copy'"
        copy_plugin(plugin)
        init_git(plugin)
        commit(plugin)
        revision = checked(["git", "rev-parse", "HEAD"], cwd=plugin).stdout.strip()
        env = os.environ.copy()
        env.pop(
            "PYTHONPATH", None
        )  # Exercise the installed package, not source imports.
        env["PRE_COMMIT_HOME"] = str(root / "pre-commit-cache")
        env["PREK_HOME"] = str(root / "prek-cache")
        env["VIRTUALENV_OVERRIDE_APP_DATA"] = str(root / "virtualenv-cache")
        env["PIP_CACHE_DIR"] = str(root / "pip-cache")
        if not real:
            install_fake_bazel(root / "bin", env)
        for runner in ("pre-commit", "prek"):
            with self.subTest(runner=runner, real=real):
                workspace = root / f"{runner} workspace"
                shutil.copytree(ROOT / "tests/fixture", workspace)
                (workspace / "file with spaces.txt").write_text("fixture\n")
                (workspace / ".gitignore").write_text(
                    "/bazel-*\n/MODULE.bazel.lock\n/builds.log\n/fake_probe.py\n"
                )
                init_git(workspace)
                env["BAZEL_TEST_LOG"] = str(workspace / "builds.log")
                if not real:
                    probe = workspace / "fake_probe.py"
                    probe.write_text(
                        "import pathlib, sys\n"
                        "assert pathlib.Path('MODULE.bazel').is_file()\n"
                        "assert sys.argv[1:] == ['--from-target', '--check', 'file with spaces.txt']\n"
                        "assert pathlib.Path(sys.argv[-1]).read_text() == 'fixture\\n'\n"
                        "print('Probe executed successfully.')\n"
                    )
                    env["BAZEL_TEST_TOOL"] = str(probe)

                def write_config(refresh=False, workspace=workspace):
                    hooks = [
                        {
                            "id": "bazel-target",
                            "alias": alias,
                            "args": (["--refresh"] if refresh else [])
                            + ["--", target, "--check"],
                            "files": r"^file with spaces\.txt$",
                        }
                        for alias, target in [
                            ("probe", "//:probe"),
                            ("env-probe", "//:bazel_env/tools/probe"),
                        ]
                    ]
                    # JSON is valid YAML, avoiding a test-only YAML dependency.
                    (workspace / ".pre-commit-config.yaml").write_text(
                        json.dumps(
                            {
                                "repos": [
                                    {
                                        "repo": str(plugin),
                                        "rev": revision,
                                        "hooks": hooks,
                                    }
                                ]
                            }
                        )
                    )

                write_config()
                checked(["git", "add", "."], cwd=workspace)
                checked(
                    [runner, "validate-config", ".pre-commit-config.yaml"],
                    cwd=workspace,
                    env=env,
                )
                checked(
                    [
                        runner,
                        "validate-manifest",
                        str(plugin / ".pre-commit-hooks.yaml"),
                    ],
                    cwd=workspace,
                    env=env,
                )
                for _ in range(2):
                    result = checked(
                        [runner, "run", "--all-files", "--verbose"],
                        cwd=workspace,
                        env=env,
                    )
                    self.assertIn("executed successfully.", result.stdout)
                if not real:
                    self.assertEqual(
                        len((workspace / "builds.log").read_text().splitlines()), 2
                    )
                write_config(refresh=True)
                checked(
                    [runner, "run", "--all-files", "--verbose"], cwd=workspace, env=env
                )
                if not real:
                    self.assertEqual(
                        len((workspace / "builds.log").read_text().splitlines()), 4
                    )

    def test_fake_bazel_through_both_runners(self):
        self.exercise(real=False)

    @unittest.skipUnless(
        os.environ.get("BAZEL_REAL_TESTS") == "1",
        "set BAZEL_REAL_TESTS=1 for real Bazel tests",
    )
    def test_real_bazel_through_both_runners(self):
        self.exercise(real=True)
