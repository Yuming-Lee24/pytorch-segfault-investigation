# PyTorch Segfault Investigation

Investigation of intermittent segmentation faults during PyTorch training, crashes in
unrelated programs and spontaneous resets on an RTX 4090 / Core Ultra 9 285K workstation.

## Current status (2026-10-17)

**The CPU is faulty and should be replaced under warranty.** Its two fastest cores (Linux
CPUs 0 and 4) execute code incorrectly when they run in their top turbo steps, above
5.5 GHz. The NVIDIA driver, the OS, PyTorch, the RAM and the firmware are cleared. The
motherboard's voltage supply can only be cleared by testing the replacement CPU in it.

- CPU 0 crashes within a second of starting the reproducer. CPU 4 crashes about once in
  20 seconds. Both are clean when held to 5.4 GHz, and the other 22 CPUs are clean.
- **Current firmware does not fix it.** After the update to BIOS 1.AE0 (microcode
  0x121), CPU 0 crashed in 22 of 22 runs and reset the machine with the same machine
  check as before: CPU 0, bank 3, status `0xbe000000e1c40400`.
- Four fatal machine-check records have been captured, three on CPU 0 and one on CPU 4,
  all with that status word.

For the warranty claim, see [DEBUG_REPORT.md](DEBUG_REPORT.md) §6 Step 4 (summary of the
evidence), §4.10 (the re-test on current firmware) and §1 (the whole investigation).

## Reproduce it

No GPU, no root and no PyTorch are needed. **It can reset the machine**, because the
faulty cores also raise fatal machine checks.

```bash
.pixi/envs/default/bin/python scripts/reproduce_crash.py                # CPU 0: crashes within a second
.pixi/envs/default/bin/python scripts/reproduce_crash.py --busy 2,3    # CPU 0 held to 5.4 GHz: passes
.pixi/envs/default/bin/python scripts/reproduce_crash.py --cpu 4 --max 60 --keep-going   # a few crashes
.pixi/envs/default/bin/python scripts/reproduce_crash.py --cpu 1       # any other core: passes
```

- Run it with nothing else heavy running. A core only reaches its top speed when the
  others are idle, and the script says so if a pass was too slow to count.
- After any spontaneous reset, run `sudo scripts/collect_root_diag.sh` first. The
  machine-check record is lost at the next reboot.

To run a job while the fault is present, keep it off both cores:

```bash
taskset -c 1-3,5-23 pixi run python torture.py
```

## Contents

| File | Purpose |
|---|---|
| [DEBUG_REPORT.md](DEBUG_REPORT.md) | Full investigation report: methodology, evidence, conclusions |
| [torture.py](torture.py) | Original reproducer: ResNet-152 + AMP training loop |
| [scripts/reproduce_crash.py](scripts/reproduce_crash.py) | The reproducer: one-second runs pinned to one CPU |
| [scripts/core_probe.py](scripts/core_probe.py) | Earlier per-CPU test and self-check |
| [scripts/cpu_conditions.sh](scripts/cpu_conditions.sh) | Compares conditions on one CPU in interleaved blocks |
| [scripts/run_torture_loop.sh](scripts/run_torture_loop.sh) | Runs `torture.py` repeatedly, optionally confined to a CPU list |
| [scripts/collect_root_diag.sh](scripts/collect_root_diag.sh) | Root-only capture of machine-check records, BERT, MSRs |
| [scripts/decode_mcelog.py](scripts/decode_mcelog.py), [scripts/decode_bert.py](scripts/decode_bert.py) | Decoders for those captures |
| [logs/reproduce/](logs/reproduce/) | Reproducer results per CPU and condition |
| [logs/core_probe/](logs/core_probe/) | Earlier per-CPU test results |
| [logs/forensics/](logs/forensics/) | `gdb` summaries of crash cores |
| [logs/rootdiag/](logs/rootdiag/) | Root captures, including the four decoded machine-check records |
| [logs/kernel/](logs/kernel/) | Kernel logs of 2026-10-07 |
| [logs/agent_reports/](logs/agent_reports/) | Supporting analyses and firmware research, with sources |
| [logs/torture/](logs/torture/) | `torture.py` runs |
| [logs/gpu_burn/](logs/gpu_burn/), [logs/memtester/](logs/memtester/), [0510-test-result/](0510-test-result/) | Stress and memory tests that passed |
