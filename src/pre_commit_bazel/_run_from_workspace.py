"""Bazel run_under helper, also runnable directly by the installed interpreter."""

import os
import sys


def main() -> int:
    try:
        count = int(sys.argv[1])
        if count < 0 or len(sys.argv) < count + 3:
            raise ValueError("invalid argument count")
        arguments = sys.argv[2 : count + 2]
        command = sys.argv[count + 2 :]
        os.chdir(os.environ["BUILD_WORKSPACE_DIRECTORY"])
        os.execv(command[0], [*command, *arguments])
    except (IndexError, KeyError, ValueError) as error:
        print(f"bazel-target: invalid Bazel launcher context: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"bazel-target: {error}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126


if __name__ == "__main__":
    raise SystemExit(main())
