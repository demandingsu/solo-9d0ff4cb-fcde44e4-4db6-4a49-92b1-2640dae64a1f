#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/.pylib/lib/python3.11/site-packages${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m pytest "$@"
