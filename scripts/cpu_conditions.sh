#!/usr/bin/env bash
# Compare test conditions on one CPU in small interleaved blocks, so that
# bursts of failures and slow drift hit every condition equally.
#   scripts/cpu_conditions.sh                      # CPU 0, 15 rounds of 10 imports each
#   CPU=4 ROUNDS=15 BLOCK=10 scripts/cpu_conditions.sh
# Conditions, in random order within each round:
#   alone   nothing else running
#   one_p   one other P-core busy (the CPU under test keeps its 57x turbo limit)
#   two_p   two other P-cores busy (the limit drops to 54x)
#   ssbd    alone, with speculative store bypass disabled for the process
set -u
cd "$(dirname "$0")/.."

CPU=${CPU:-0}
ROUNDS=${ROUNDS:-15}
BLOCK=${BLOCK:-10}
PY=.pixi/envs/default/bin/python
OUT=logs/core_probe/$(date +%Y%m%d_%H%M%S)_conditions_cpu${CPU}.tsv
ALL=0-$(($(nproc --all) - 1))
SSBD='import ctypes; ctypes.CDLL(None).prctl(53, 0, 4, 0, 0); import torch, torchvision'

# Two P-cores other than the one under test.
others=()
for c in 2 3 5 6; do
    [ "$c" != "$CPU" ] && others+=("$c")
done

run() {
    taskset -c "$ALL" "$PY" scripts/core_probe.py sweep --mode spawn --cpus "$CPU" \
        --count "$BLOCK" --out "$OUT" "$@" > /dev/null || exit $?
}

for r in $(seq 1 "$ROUNDS"); do
    for arm in $(shuf -e alone one_p two_p ssbd); do
        case $arm in
            alone) run --tag alone ;;
            one_p) run --tag one_p --load-cpus "${others[0]}" ;;
            two_p) run --tag two_p --load-cpus "${others[0]},${others[1]}" ;;
            ssbd)  run --tag ssbd --code "$SSBD" ;;
        esac
    done
done
echo "Wrote $OUT"
