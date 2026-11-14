#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "$0")/.." && pwd -P)
task_tmp=$(mktemp -d)
trap 'rm -rf "$task_tmp"' EXIT
mkdir -p "$task_tmp/fake-bin" "$task_tmp/work space" "$task_tmp/plugin 'copy'"
# Exercise run_under quoting when the plugin path includes spaces and quotes.
cp -R "$repo_dir/hooks" "$task_tmp/plugin 'copy'/"
wrapper="$task_tmp/plugin 'copy'/hooks/bazel-target"
cd "$task_tmp/work space"
git init -q
touch MODULE.bazel
export BAZEL_TEST_LOG="$task_tmp/bazel.log"
export BAZEL_TEST_TOOL="$task_tmp/tool"
export PATH="$task_tmp/fake-bin:$PATH"

cat > "$task_tmp/fake-bin/bazel" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 4 && "$1" == run && "$2" == --script_path=* && "$3" == --run_under=* ]]
printf '%s\n' "$4" >> "$BAZEL_TEST_LOG"
if [[ ${BAZEL_TEST_FAILURE:-0} != 0 ]]; then exit "$BAZEL_TEST_FAILURE"; fi
launcher=${2#--script_path=}
if [[ ${BAZEL_TEST_NO_OUTPUT:-0} == 1 ]]; then exit 0; fi
printf -v command '%s %q' "${3#--run_under=}" "$BAZEL_TEST_TOOL"
printf '#!/usr/bin/env bash\nset -euo pipefail\nexport BUILD_WORKSPACE_DIRECTORY=%q\ncd /\nexec /bin/bash -c %q "$@"\n' \
    "$PWD" "$command" > "$launcher"
chmod +x "$launcher"
printf 'Built launcher\n'
SH
cat > "$BAZEL_TEST_TOOL" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'cwd=%s\n' "$PWD"
printf 'arg=<%s>\n' "$@"
exit "${TOOL_TEST_STATUS:-0}"
SH
chmod +x "$task_tmp/fake-bin/bazel" "$BAZEL_TEST_TOOL"

run() {
    status=0
    "$wrapper" "$@" > "$task_tmp/stdout" 2> "$task_tmp/stderr" || status=$?
}
expect_status() {
    if [[ "$status" != "$1" ]]; then
        cat "$task_tmp/stdout" "$task_tmp/stderr" >&2
        printf 'Expected status %s, got %s\n' "$1" "$status" >&2
        exit 1
    fi
}
contains() { grep -F -- "$2" "$task_tmp/$1" > /dev/null; }
build_count() { [[ $(wc -l < "$BAZEL_TEST_LOG" | tr -d ' ') == "$1" ]]; }

run -- //:probe 'file with spaces.txt' '$(touch unexpected)' '*.txt' '--flag=value'
expect_status 0
contains stdout "cwd=$PWD"
contains stdout 'arg=<file with spaces.txt>'
contains stdout 'arg=<$(touch unexpected)>'
contains stdout 'arg=<*.txt>'
contains stderr 'Built launcher'
[[ ! -e unexpected ]]
! grep -F 'Built launcher' "$task_tmp/stdout"
build_count 1

export BAZEL_TEST_FAILURE=91
run -- //:probe 'new arguments'
expect_status 0
contains stdout 'arg=<new arguments>'
! grep -F 'file with spaces.txt' "$task_tmp/stdout"
build_count 1
export TOOL_TEST_STATUS=17
run -- //:probe
expect_status 17
build_count 1
unset TOOL_TEST_STATUS
run --refresh -- //:probe
expect_status 91
# A failed refresh must retain the previous complete launcher and remove temps.
run -- //:probe
expect_status 0
[[ -z $(find .git/pre-commit-bazel -name '.launcher.*' -print) ]]
unset BAZEL_TEST_FAILURE
run --refresh -- //:probe
expect_status 0
build_count 3
run -- //tools:other
expect_status 0
run -- @tools//:probe
expect_status 0
run -- @@tools+//:probe
expect_status 0
run -- //:bazel_env/tools/probe
expect_status 0
build_count 7

export BAZEL_TEST_NO_OUTPUT=1
run -- //:empty
expect_status 2
contains stderr 'did not generate an executable launcher'
unset BAZEL_TEST_NO_OUTPUT
for label in '--flag' 'probe' '//tools' '//...' '//tools:all' '//tools:all-targets' '//tools:*' '//tools:?' '//:one //:two'; do
    run -- "$label"
    expect_status 2
done
run --refresh
expect_status 2
run --unknown
expect_status 2
run
expect_status 2
run --
expect_status 2
run --help
expect_status 0
contains stdout 'Usage:'

# Cache separation follows Git's per-worktree metadata directory.
git -c user.name=Test -c user.email=test@example.invalid -c commit.gpgsign=false commit --allow-empty -qm fixture
git worktree add -q -b test-worktree "$task_tmp/worktree"
cd "$task_tmp/worktree"
touch MODULE.bazel
run -- //:probe
expect_status 0
contains stdout "cwd=$PWD"
build_count 9

# A warm cache executes without even having Bazel installed on PATH.
mkdir "$task_tmp/no-bazel-bin"
for tool in bash git dirname; do
    ln -s "$(command -v "$tool")" "$task_tmp/no-bazel-bin/$tool"
done
status=0
PATH="$task_tmp/no-bazel-bin" "$wrapper" -- //:probe > "$task_tmp/stdout" 2> "$task_tmp/stderr" || status=$?
expect_status 0
status=0
PATH="$task_tmp/no-bazel-bin" "$wrapper" -- //:missing > "$task_tmp/stdout" 2> "$task_tmp/stderr" || status=$?
expect_status 2
contains stderr 'bazel is required on PATH'

mkdir nested
cd nested
touch MODULE.bazel
run -- //:probe
expect_status 2
contains stderr 'Git repository root'
cd "$task_tmp"
run -- //:probe
expect_status 2
contains stderr 'MODULE.bazel is missing'
printf '%s\n' 'Wrapper integration tests passed.'
