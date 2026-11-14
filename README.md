# pre-commit-bazel

Run executable Bazel targets with **pre-commit** or **prek**, using your project's
pinned tools. On first use, the Bash wrapper builds the target and caches a
Bazel-generated launcher. Later invocations execute that launcher without
starting Bazel.

## Requirements

- Linux or macOS, with Bash 3.2 or newer and Git on `PATH`.
- `bazel` on `PATH` for initial setup and refresh (a Bazelisk launcher works).
- pre-commit 4.4+ or prek with `unsupported_script` support.
- The consuming Git repository root must also be the Bazel workspace root,
  containing `MODULE.bazel`. Nested workspaces are not supported.

No Python dependency is needed by the wrapper. The hook uses
`language: unsupported_script`, supported by both runners. The integration suite
tests Bazel 8.4.2.

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
hooks/bazel-target [--refresh] -- TARGET [ARGS...]
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

Launchers live under `pre-commit-bazel/v1` in the consuming worktree's Git metadata
directory. They are keyed by target label and plugin checkout location. No
`.gitignore` entry is needed. Each target and worktree has its own cache entry;
concurrent bootstrap attempts publish complete launchers atomically.

Existing launchers are reused without checking dependencies or invoking Bazel.
After changing dependencies, `.bazelrc`, target runtime settings, or after
`bazel clean`, explicitly regenerate the launcher. For an installed hook,
temporarily add `--refresh` before the argument separator and run that hook:

```yaml
args: [--refresh, --, //tools:buildifier, -mode=check]
```

Remove `--refresh` afterward to resume cached execution. You can also invoke
the wrapper by absolute path from the consuming workspace:

```sh
/path/to/pre-commit-bazel/hooks/bazel-target --refresh -- //tools:buildifier -mode=check BUILD.bazel
```

That direct invocation has a separate cache entry if its plugin location differs
from the runner's cached checkout. Refresh through the same entry point you use
for normal execution. To reset all entries for a worktree, remove its
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
bash tests/test-wrapper.sh
bash tests/test-runners.sh
bash tests/test-runners.sh --real
```

Runner tests require both pre-commit and prek. `--real` also requires Bazel and
network access to build the pinned fixture. Tests use temporary repositories;
they do not install Git hooks into this checkout. CI runs on Linux and macOS.
