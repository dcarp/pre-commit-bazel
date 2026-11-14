"""Build and cache a Bazel-generated launcher, then replace this process with it."""

import argparse
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class HookError(Exception):
    def __init__(self, message: str, status: int = 2):
        super().__init__(message)
        self.status = status


def parse_arguments(argv: list[str]) -> tuple[bool, str, list[str]]:
    parser = argparse.ArgumentParser(
        prog="bazel-target",
        usage="%(prog)s [--refresh] -- TARGET [ARGS...]",
        description="Build an executable Bazel target once and reuse its launcher.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--refresh", action="store_true", help="regenerate the target launcher"
    )
    if "--" not in argv:
        parser.parse_args(argv)  # Honor --help and report unknown wrapper options.
        parser.error("-- followed by an executable TARGET is required")
    separator = argv.index("--")
    options = parser.parse_args(argv[:separator])
    remaining = argv[separator + 1 :]
    if not remaining:
        parser.error("an executable TARGET is required after --")
    target, *arguments = remaining
    if not re.fullmatch(r"(?:@@?[^/\s]+)?//[^:\s]*:[^:\s]+", target):
        parser.error(
            "TARGET must be an explicit label such as //tools:buildifier or @repo//:tool"
        )
    if any(char in target for char in "*?[]") or target.endswith(
        ("/...", ":all", ":all-targets")
    ):
        parser.error("target patterns are not supported; provide one executable target")
    return options.refresh, target, arguments


def git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise HookError("run from a Git working tree")
    return result.stdout.rstrip("\n")


def launcher_path(target: str) -> Path:
    if not Path("MODULE.bazel").is_file():
        raise HookError(
            "run from the consuming Bazel workspace root (MODULE.bazel is missing)"
        )
    if shutil.which("git") is None:
        raise HookError("git is required on PATH")
    git_dir = Path(git_output("--absolute-git-dir"))
    if git_output("--show-prefix"):
        raise HookError("the Git repository root must also be the Bazel workspace root")
    # Preserve the virtual environment's interpreter path instead of resolving
    # its symlink to a system Python that cannot import the installed package.
    identity = (
        target,
        str(Path(__file__).resolve().parent),
        os.path.abspath(sys.executable),
    )
    key = hashlib.sha256(b"\0".join(os.fsencode(part) for part in identity)).hexdigest()
    return git_dir / "pre-commit-bazel" / "v2" / key


def build_launcher(target: str, destination: Path) -> None:
    if shutil.which("bazel") is None:
        raise HookError("bazel is required on PATH to build the target launcher")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".launcher.", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        helper = Path(__file__).resolve().with_name("_run_from_workspace.py")
        # With run_under, Bazel's script invokes bash -c and supplies launcher
        # arguments as shell positional parameters. Pass their count and values
        # before the executable and its declared arguments, which Bazel appends.
        run_under = (
            shlex.join([os.path.abspath(sys.executable), str(helper)]) + ' "$#" "$@"'
        )
        result = subprocess.run(
            [
                "bazel",
                "run",
                f"--script_path={temporary}",
                f"--run_under={run_under}",
                target,
            ],
            stdout=sys.stderr,
            check=False,
        )
        if result.returncode:
            status = (
                result.returncode if result.returncode > 0 else 128 - result.returncode
            )
            raise HookError(f"Bazel failed to generate a launcher for {target}", status)
        if (
            not temporary.is_file()
            or not temporary.stat().st_size
            or not os.access(temporary, os.X_OK)
        ):
            raise HookError("Bazel did not generate an executable launcher")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    refresh, target, arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        launcher = launcher_path(target)
        if refresh or not launcher.is_file() or not os.access(launcher, os.X_OK):
            build_launcher(target, launcher)
        # bash -c consumes the first launcher argument as $0, leaving actual
        # hook arguments in "$@" for our run_under helper.
        os.execv(launcher, [str(launcher), "bazel-target", *arguments])
    except HookError as error:
        print(f"bazel-target: {error}", file=sys.stderr)
        return error.status
    except OSError as error:
        print(f"bazel-target: {error}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126
