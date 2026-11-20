#!/usr/bin/env bash
# Run a repro script under every pixi interpreter environment and every interpreter
# built in .scratch/build/ (if any). Prints one block per interpreter.
#
#   bash tools/run-matrix.sh repro/gc_order_perf.py --check-order
set -uo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
scratch=${SCRATCH:-$here/.scratch}
cd "$here"
for env in py310 py312 py31314 py31318 py3146 py31410 py315 ft3146 ft31410; do
  echo "[$env]"
  pixi run -e "$env" python "$@" 2>&1 | sed 's/^/  /'
done
for py in "$scratch"/build/*/python; do
  [ -x "$py" ] || continue
  echo "[$(basename "$(dirname "$py")")]"
  "$py" "$@" 2>&1 | sed 's/^/  /'
done
