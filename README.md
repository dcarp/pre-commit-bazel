# pre-commit-bazel

Run executable Bazel targets with **pre-commit** or **prek**, using your project's
pinned tools. On first use, the Python wrapper builds the target and caches a
Bazel-generated launcher. Later invocations execute that launcher without
starting Bazel.

## Requirements

- Linux or macOS, with Python 3.11+ and Git on `PATH`.
- Bash for Bazel's generated launchers (normally provided by the OS).
- `bazel` on `PATH` for initial setup and refresh (a Bazelisk launcher works).
- pre-commit or prek with Python hook support.
- The consuming Git repository root must also be the Bazel workspace root,
  containing `MODULE.bazel`. Nested workspaces are not supported.

The hook uses `language: python`: the runner installs this package into its
managed Python environment. No manual package installation is needed for hook
usage, and the plugin has no third-party runtime dependencies. An appropriate
Python interpreter must be available to the runner. Bazel remains an external
prerequisite. The integration suite tests Bazel 8.4.2.

## Configure hooks

Add the following to `.pre-commit-config.yaml`, replacing `<commit-sha>` with a
published tag or commit SHA.

```yaml
repos:
  - repo: https://github.com/dcarp/pre-commit-bazel
    rev: <commit-sha>
    hooks:
      - id: bazel-target
        alias: buildifier
        name: buildifier
        args: [--, //tools:buildifier, -mode=check]
        types: [bazel]
      - id: bazel-target
        alias: ruff
        name: ruff check
        args: [--, '@tools//:ruff', check]
        types_or: [python, pyi]
```

Repeat `bazel-target` with different aliases, targets, arguments, and filters.
The target must be one executable label, such as `//tools:buildifier` or
`@tools//:ruff`; target patterns and test-suite execution are not supported.
The wrapper interface is:

```text
bazel-target [--refresh] -- TARGET [ARGS...]
```

Everything after the target belongs to the tool; the runner appends matching
filenames. Arguments are passed literally, without shell expansion. Set
`pass_filenames: false` for targets that do not accept filenames, and
`always_run: true` when they should run without matching files.

Install and run with either runner:

```sh
pre-commit install
pre-commit run --all-files
# Or:
prek install
prek run --all-files
```

## Build once and refresh explicitly

On first use, the wrapper calls `bazel run --script_path=... TARGET`, supplying a
helper through `--run_under` to run the executable from the repository root.
Bazel builds the target and generates a launcher without executing the tool.
The wrapper executes that launcher with the current arguments and filenames.

Launchers live under `pre-commit-bazel/v2` in the consuming worktree's Git metadata
directory. They are keyed by target label, installed package location, and Python
interpreter path. Earlier `v1` Bash launchers are left untouched and are not
reused. No `.gitignore` entry is needed. Each target and worktree has its own cache entry;
concurrent bootstrap attempts publish complete launchers atomically.

Existing launchers are reused without checking dependencies or invoking Bazel.
After changing dependencies, `.bazelrc`, target runtime settings, or after
`bazel clean`, explicitly regenerate the launcher. For an installed hook,
temporarily add `--refresh` before the argument separator and run that hook:

```yaml
args: [--refresh, --, //tools:buildifier, -mode=check]
```

Remove `--refresh` afterward to resume cached execution. For standalone use,
install the package into your Python environment, then invoke the command from
the consuming workspace:

```sh
python -m pip install /path/to/pre-commit-bazel
bazel-target --refresh -- //tools:buildifier -mode=check BUILD.bazel
# Equivalent module entry point:
python -m pre_commit_bazel --refresh -- //tools:buildifier -mode=check BUILD.bazel
```

That direct invocation has a separate cache entry if its package location or
interpreter differs from the runner's environment. Refresh through the same entry
point you use for normal execution. To reset all entries for a worktree, remove its
`pre-commit-bazel` directory under `git rev-parse --absolute-git-dir`.

The launcher retains target-declared arguments and runtime settings captured by
Bazel during bootstrap. It references artifacts in Bazel's output tree, so it is
not a standalone distribution. Failures pass through without automatic retries;
missing artifacts require a refresh. Bazel serializes builds, and filename
batches within each hook run serially.

## Working directory and runfiles

Tools execute from the consuming repository root, so repository-relative filenames
and configuration discovery work naturally. Bazel prepares runfiles during
bootstrap, but the target must locate them independently of its current working
directory, for example through its language's runfiles library. Targets that
assume they start inside the runfiles directory need adaptation.

The wrapper preserves tool stdout, stderr, and exit status; bootstrap output goes
to stderr. It does not add tools to `PATH` or install Bazel. Tool versions and
build settings belong in the consuming project's Bazel configuration.

[`bazel_env.bzl`](https://github.com/buildbuddy-io/bazel_env.bzl) is optional. Its
generated executable tool targets can be selected like any other executable:

```yaml
args: [--, //:bazel_env/tools/buildifier, -mode=check]
```

## Development

```sh
python -m pip install -e .
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
BAZEL_REAL_TESTS=1 python -m unittest discover -s tests -p test_runners.py -k test_real_bazel -v
```

Runner tests require both pre-commit and prek and install the plugin into each
runner's own environment. Real Bazel tests also require Bazel and network access
to build the pinned fixture. Tests use temporary repositories; they do not
install Git hooks into this checkout. The small Bash probe is a Bazel fixture,
not part of the plugin runtime. CI tests Python 3.11 and 3.14 on Linux and macOS,
with real Bazel integration on Python 3.14.

## Dependency updates

Install the hosted [Renovate GitHub App](https://github.com/apps/renovate) and
grant it access to this repository. Once `renovate.json` is on the default
branch, the App manages updates without a scheduled workflow or bot-token secret.
Its Dependency Dashboard issue tracks pending updates and any required actions.

The configuration uses [`config:best-practices`](https://docs.renovatebot.com/presets-config/#configbest-practices)
without overrides. This includes GitHub Actions SHA pinning, recommended update
grouping, development dependency pinning, and applicable lock-file maintenance.
Updates require manual merging by default. The preset's default path exclusions
apply, including test directories, so the Bazel fixture is not scanned.
Release Please continues to manage the package version.

## Releases

[Release Please](https://github.com/googleapis/release-please) runs on pushes to
`main` and can also be started manually from GitHub Actions. Conventional commits
such as `feat: ...` and `fix: ...` accumulate into a release PR that updates
`pyproject.toml`, `CHANGELOG.md`, and the release manifest. Merging that PR creates
a GitHub release and a tag such as `v0.1.0`, which consumers can use as their hook
`rev`. The first release starts at `0.1.0`; breaking changes before `1.0.0` bump
the minor version. Package publication to PyPI is not configured.

In the repository's Actions settings, enable **Allow GitHub Actions to create
and approve pull requests**. The workflow uses `GITHUB_TOKEN` by default.
GitHub does not trigger other workflows for PRs and tags created with that token.
To run CI automatically on release PRs, configure the `RELEASE_PLEASE_TOKEN`
Actions secret with a token that can write repository contents, issues, and pull
requests. The workflow uses that token when present.
