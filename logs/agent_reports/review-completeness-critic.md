## Verdict per claim

- **K1: SURVIVES, narrowly.** CPU 0 at 57x failed 27/470; all other CPUs 0/585. But CPU 4, the only other 57x core, has only 95 imports and 180 s steady. None of the 7 torture.py segfaults has a CPU (/home/yuming/pytorch-segfault-investigation/logs/agent_reports/torture-logs.md); seconds before reset #1 the one busy thread was on CPU 4 at 5648 MHz (/home/yuming/pytorch-segfault-investigation/logs/agent_reports/memtest-occt.md).
- **K2: SURVIVES.** Three register-only impossible faults (pid 27451, oops line 1241, update-manager). Caveat: 10 of 20 python3.11 fault lines share offset 0x218228, so one code path dominates; no self-check digest ever mismatched.
- **K3: WEAKENED.** Only 57x and 54x were run, and the cap was indirect (CPUs 2+3 busy) with no one-busy-P-core control. 175 of the 200 capped spawns lie inside a window (14:36:12–14:42:47) where 98 consecutive uncapped 5.7 GHz spawns passed too. Failures are bursty, so "1 in 100,000" (DEBUG_REPORT.md §4.8.2) overstates.
- **K4: WEAKENED.** One record, from the provoked reset; the two spontaneous resets have none. ARL050's title requires a C1 exit, yet steady mode never sleeps (/home/yuming/pytorch-segfault-investigation/scripts/core_probe.py:262-266).
- **K5: WEAKENED.** Inference: a design erratum should also hit CPU 4 at the same ratio. The firmware test decides one way only: a pass may mean more voltage, or CPU 0 no longer reaching 57x. "55x–57x" is extrapolation.
- **K6: WEAKENED.** Holds for today's reproducer. The April driver-590 crashes (two in step window 1001–1100, no CPU, no core) could be a separate bug: Ubuntu 24 shows 0 crashes in 6,276 steady steps. PSU and board were never swapped.
- **K7: WEAKENED.** A BIOS 54x cap is untested. `taskset -c 1-23` leaves kernel, desktop and unattended-upgrade on CPU 0; that job ran at both spontaneous resets and next fires Thu 06:25:43.

## Strongest objection

K1 and K3 rest on about 670 one-second imports from one afternoon, with bursty failures and frequency never set directly. The original complaint is tied to CPU 0 only by analogy: the CPUs 1–23 torture A/B stands at 8 clean 75 s launches against a 3/6 baseline (CI 12–88%).

## Errors or overstatements found

- "All fault lines that name a CPU name CPU 0" is false: /home/yuming/pytorch-segfault-investigation/logs/kernel/boot_20261007_132308_kernel.log:1236 says "CPU 22". It is strlen(NULL), probably a deliberate test, but undocumented.
- core_probe.py:328 reads thermal_zone4, which is `iwlwifi_1`; every `max_temp_c` is the Wi-Fi card.
- The harness logs avg/max MHz but never checks them, so a capped CPU 0 passes vacuously. During the background torture loop CPU 4 reached ≥5.6 GHz in 21/48 samples.
- No single documented reproducer command; README.md and DEBUG_REPORT.md §5–§10 still describe the RAM hypothesis.
- Fault lines after 14:10 are missing from /home/yuming/pytorch-segfault-investigation/logs/kernel/; TSVs omit `--code` (the "300 spawns" rows are `python -c pass`); agent reports cite scratch files the reset erased.
- Unreported lead: /home/yuming/pytorch-segfault-investigation/logs/rootdiag/20261007_143159/perf_status_samples.tsv shows CPU 0 requesting 1.319 V at 57x (n=2), CPU 4 1.361 V (n=1); encoding unvalidated.

## Evidence I verified myself

- Spawn totals and frequencies, burst/steady rows, MSRs 0x1ad, 0x610, 0x771, forensics registers, 15 CPU-0 segfault plus 5 GP lines, microcode, BIOS, ME: all match.
- /home/yuming/pytorch-segfault-investigation/logs/rootdiag/20261007_143159/mcelog.bin decodes as claimed. Its ADDR=0x5b9d2564a239 has page offset 0x239, matching python3.11 offset 0x1ee239, the instruction after crash site 0x1ee235 (pids 26758, 16879). Inference: the reset struck the same interpreter code.
- strace on CPUs 8–23: the import opens no `/dev/nvidia*` and creates no threads.
- Not checked: Intel's erratum text, the update-manager core.

## Tests that would settle what is still open

Rootless:
1. Interleaved 10-spawn blocks on CPU 0: no load, CPU 2 busy (still 57x), CPUs 2+3, CPUs 8+12; 40 blocks each, equal exposure on CPU 4.
2. At least 24 torture.py launches on CPUs 1–23; read the CPU from each core dump's rseq area.
3. Any "fixed" verdict needs 470 spawns over two boots with max ≥5.65 GHz; 52 give 95% only if failures were independent.

Root or BIOS:
4. Per-CPU HWP maximum stepped 54–57x on CPU 0 alone; MSR 0x198 for CPUs 0 and 4 under load.
5. Photograph BIOS settings, then microcode 0x11b, then BIOS.
6. For RMA: an mprime or OCCT single-core failure on core 0, FPO/ATPO, a second board.

Top three by value per effort: (a) harness frequency guard, package-temperature fix and test 1; (b) `mce=print_all` before Thursday 06:25; (c) test 4.
