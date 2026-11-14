"""Shared temporary-repository and fake-Bazel helpers for integration tests."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, *, cwd, env=None):
    return subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def checked(command, *, cwd, env=None):
    result = run(command, cwd=cwd, env=env)
    if result.returncode:
        raise AssertionError(
            f"{command!r} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
    return result


def init_git(workspace):
    checked(["git", "init", "-q"], cwd=workspace)


def commit(workspace):
    checked(["git", "add", "."], cwd=workspace)
    checked(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        cwd=workspace,
    )


def copy_plugin(destination):
    destination.mkdir()
    shutil.copytree(
        ROOT / "src",
        destination / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    for name in ("pyproject.toml", "README.md", ".pre-commit-hooks.yaml"):
        shutil.copy2(ROOT / name, destination / name)


def python_executable(path, script, interpreter=sys.executable):
    # A tiny executable shim permits Python interpreter paths containing spaces.
    path.write_text(
        "#!/bin/sh\nexec " + shlex.join([str(interpreter), str(script)]) + ' "$@"\n'
    )
    path.chmod(0o755)


def install_fake_bazel(directory, env):
    directory.mkdir()
    python_executable(directory / "bazel", Path(__file__).resolve())
    env["PATH"] = str(directory) + os.pathsep + env.get("PATH", "")


def fake_bazel():
    args = sys.argv[1:]
    assert len(args) == 4 and args[0] == "run"
    assert args[1].startswith("--script_path=") and args[2].startswith("--run_under=")
    with open(os.environ["BAZEL_TEST_LOG"], "a") as log:
        log.write(json.dumps(args[-1]) + "\n")
    status = int(os.environ.get("BAZEL_TEST_FAILURE", "0"))
    if status:
        return status
    if os.environ.get("BAZEL_TEST_NO_OUTPUT") == "1":
        return 0
    launcher = Path(args[1].split("=", 1)[1])
    command = (
        args[2].split("=", 1)[1]
        + " "
        + shlex.join(
            [
                sys.executable,
                os.environ["BAZEL_TEST_TOOL"],
                "--from-target",
            ]
        )
    )
    launcher.write_text(
        "#!/bin/bash\nexport BUILD_WORKSPACE_DIRECTORY="
        + shlex.quote(str(Path.cwd()))
        + "\ncd /\nexec /bin/bash -c "
        + shlex.quote(command)
        + ' "$@"\n'
    )
    launcher.chmod(0o700)
    print("Built launcher")
    return 0


if __name__ == "__main__":
    raise SystemExit(fake_bazel())
