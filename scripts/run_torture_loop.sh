#!/usr/bin/env bash
# Run torture.py repeatedly and record how each run ended.
#   RUNS=6 CAP=480 scripts/run_torture_loop.sh
#   CPUS=1-23 RUNS=8 CAP=60 scripts/run_torture_loop.sh   # keep it off CPU 0
# Core dumps are enabled; on Ubuntu apport writes them to /var/lib/apport/coredump/.
set -u
cd "$(dirname "$0")/.."

RUNS=${RUNS:-6}
CAP=${CAP:-480}
CPUS=${CPUS:-}
PIXI=${PIXI:-$HOME/.pixi/bin/pixi}
STAMP=$(date +%Y%m%d_%H%M%S)
SUMMARY=logs/torture/summary_${STAMP}.tsv

mkdir -p logs/torture
ulimit -c unlimited
export CUDA_LAUNCH_BLOCKING=1 TORCH_SHOW_CPP_STACKTRACES=1 PYTHONFAULTHANDLER=1

printf '# cpus=%s cap=%ss\n' "${CPUS:-all}" "$CAP" | tee "$SUMMARY"
printf 'run\tstart\tend\texit\tlast_step\tlog\n' | tee -a "$SUMMARY"
for i in $(seq 1 "$RUNS"); do
    start=$(date +%FT%T)
    out=logs/torture/stdout_${STAMP}_run${i}.log
    timeout "$CAP" ${CPUS:+taskset -c "$CPUS"} "$PIXI" run python torture.py > "$out" 2>&1
    rc=$?
    end=$(date +%FT%T)
    log=$(sed -n 's/^Log: //p' "$out" | head -1)
    last=$(grep -a '^>>> step' "$out" | tail -1 | awk '{print $3}')
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$start" "$end" "$rc" "${last:-0}" "${log:-none}" | tee -a "$SUMMARY"
    sync
done
