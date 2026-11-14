#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "$0")/.." && pwd -P)
task_tmp=$(mktemp -d)
cleanup() {
    result=$?
    if [[ "$result" != 0 && ${KEEP_TEST_TMP:-0} == 1 ]]; then
        printf 'Test files retained at %s\n' "$task_tmp" >&2
    else
        rm -rf "$task_tmp"
    fi
}
trap cleanup EXIT
export PRE_COMMIT_HOME="$task_tmp/pre-commit-cache"
export PREK_HOME="$task_tmp/prek-cache"
mode=${1:-fake}
[[ "$mode" == fake || "$mode" == --real ]] || { echo 'Usage: test-runners.sh [--real]' >&2; exit 2; }
for runner in pre-commit prek; do
    command -v "$runner" > /dev/null || { printf '%s is required\n' "$runner" >&2; exit 1; }
done

# Test a remote-style checkout, including helper paths with spaces and quotes.
plugin="$task_tmp/plugin 'copy'"
mkdir "$plugin"
cp -R "$repo_dir/hooks" "$repo_dir/.pre-commit-hooks.yaml" "$plugin/"
git -C "$plugin" init -q
git -C "$plugin" add .
git -C "$plugin" -c user.name=Test -c user.email=test@example.invalid -c commit.gpgsign=false commit -qm fixture
plugin_rev=$(git -C "$plugin" rev-parse HEAD)

if [[ "$mode" == fake ]]; then
    mkdir "$task_tmp/fake-bin"
    cat > "$task_tmp/fake-bin/bazel" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 4 && "$1" == run && "$2" == --script_path=* && "$3" == --run_under=* ]]
[[ "$4" == //:probe || "$4" == //:bazel_env/tools/probe ]]
printf '%s\n' "$4" >> builds.log
launcher=${2#--script_path=}
printf -v command '%s %q --from-target' "${3#--run_under=}" "$PWD/fake-probe"
printf '#!/usr/bin/env bash\nexport BUILD_WORKSPACE_DIRECTORY=%q\ncd /\nexec /bin/bash -c %q "$@"\n' \
    "$PWD" "$command" > "$launcher"
chmod +x "$launcher"
SH
    chmod +x "$task_tmp/fake-bin/bazel"
    export PATH="$task_tmp/fake-bin:$PATH"
fi

write_config() {
    cat > .pre-commit-config.yaml <<YAML
repos:
  - repo: '${plugin//\'/\'\'}'
    rev: '$plugin_rev'
    hooks:
      - id: bazel-target
        alias: probe
        args: [$1--, //:probe, --check]
        files: '^file with spaces\.txt$'
      - id: bazel-target
        alias: env-probe
        args: [$1--, //:bazel_env/tools/probe, --check]
        files: '^file with spaces\.txt$'
YAML
}

for runner in pre-commit prek; do
    workspace="$task_tmp/$runner workspace"
    mkdir "$workspace"
    cp -R "$repo_dir/tests/fixture/." "$workspace/"
    printf 'fixture\n' > "$workspace/file with spaces.txt"
    printf '/bazel-*\n/MODULE.bazel.lock\n/builds.log\n/fake-probe\n' > "$workspace/.gitignore"
    if [[ "$mode" == fake ]]; then
        cat > "$workspace/fake-probe" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ -f MODULE.bazel && $# -eq 3 ]]
[[ "$1" == --from-target && "$2" == --check && "$3" == 'file with spaces.txt' ]]
[[ $(cat "$3") == fixture ]]
printf '%s\n' 'Fake probe executed successfully.'
SH
        chmod +x "$workspace/fake-probe"
    fi
    git -C "$workspace" init -q
    (
        cd "$workspace"
        write_config ''
        git add .
        "$runner" validate-config .pre-commit-config.yaml
        "$runner" validate-manifest "$plugin/.pre-commit-hooks.yaml"
        "$runner" run --all-files --verbose
        "$runner" run --all-files --verbose
        if [[ "$mode" == fake ]]; then
            [[ $(wc -l < builds.log | tr -d ' ') == 2 ]]
        fi
        write_config '--refresh, '
        "$runner" run --all-files --verbose
        if [[ "$mode" == fake ]]; then
            [[ $(wc -l < builds.log | tr -d ' ') == 4 ]]
        fi
    )
done
printf '%s\n' "Runner integration tests passed ($mode)."
