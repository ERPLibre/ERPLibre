#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 \"Warning message to display\"" >&2
  exit 2
fi

msg="$1"

# Require an interactive terminal
if [[ ! -t 0 || ! -t 1 ]]; then
  echo "Interactive confirmation not possible (no TTY). Aborting." >&2
  exit 130
fi

echo "$msg"
printf "Proceed? [y/N] "
# shellcheck disable=SC2162
read -r ans

if [[ "$ans" =~ ^[yY]$ ]]; then
  exit 0
else
  echo "Aborted."
  exit 130
fi
