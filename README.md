# PyTorch Segfault Investigation

Investigation of intermittent segmentation faults during PyTorch training, crashes in
unrelated programs and spontaneous resets on an RTX 4090 / Core Ultra 9 285K workstation.

## Current status (2026-10-07)

**The fault is in the CPU.** Its first performance core (Linux CPU 0) executes code
incorrectly when it runs at top turbo speed (about 5.7 GHz). The NVIDIA driver, the OS,
PyTorch and the RAM are cleared.

- Pinned to CPU 0, `import torch` fails about 5 % of the time. On every other CPU it has
  never failed in 1,189 runs.
- Not yet settled: whether the core is defective or the 17-month-old BIOS is to blame.
  Update the BIOS, re-run the reproducer, and replace the CPU if CPU 0 still fails.

Full evidence and the step-by-step plan are in [DEBUG_REPORT.md](DEBUG_REPORT.md), §4.8, §5 and §6.

## Reproduce it

No GPU and no root are needed. This runs 300 pinned imports on each of CPUs 0 and 4 and
takes about 15 minutes. **It can reset the machine**, because CPU 0 also raises fatal
machine checks.

```bash
.pixi/envs/default/bin/python scripts/core_probe.py sweep --mode spawn --cpus 0,4 --count 50 --rounds 6 --require-mhz 5600
```

- Expected while the fault is present: CPU 0 rows show failures, CPU 4 rows show none.
- Rows marked `too_slow` did not reach top speed and prove nothing; close other programs and repeat.
- After any spontaneous reset, run `sudo scripts/collect_root_diag.sh` first. The
  machine-check record is lost at the next reboot.

To run a job while the fault is present, keep it off CPU 0:

```bash
taskset -c 1-23 pixi run python torture.py
```

## Contents

| File | Purpose |
|---|---|
| [DEBUG_REPORT.md](DEBUG_REPORT.md) | Full investigation report: methodology, evidence, conclusions |
| [torture.py](torture.py) | Original reproducer: ResNet-152 + AMP training loop |
| [scripts/core_probe.py](scripts/core_probe.py) | Per-CPU reproducer and self-check |
| [scripts/cpu_conditions.sh](scripts/cpu_conditions.sh) | Compares conditions on one CPU in interleaved blocks |
| [scripts/run_torture_loop.sh](scripts/run_torture_loop.sh) | Runs `torture.py` repeatedly, optionally confined to a CPU list |
| [scripts/collect_root_diag.sh](scripts/collect_root_diag.sh) | Root-only capture of machine-check records, BERT, MSRs |
| [scripts/decode_mcelog.py](scripts/decode_mcelog.py), [scripts/decode_bert.py](scripts/decode_bert.py) | Decoders for those captures |
| [logs/core_probe/](logs/core_probe/) | Per-CPU test results |
| [logs/forensics/](logs/forensics/) | `gdb` summaries of crash cores |
| [logs/rootdiag/](logs/rootdiag/) | Root captures, including the decoded machine-check records |
| [logs/kernel/](logs/kernel/) | Kernel logs of 2026-10-07 |
| [logs/agent_reports/](logs/agent_reports/) | Supporting analyses and firmware research, with sources |
| [logs/torture/](logs/torture/) | `torture.py` runs |
| [logs/gpu_burn/](logs/gpu_burn/), [logs/memtester/](logs/memtester/), [0510-test-result/](0510-test-result/) | Stress and memory tests that passed |
