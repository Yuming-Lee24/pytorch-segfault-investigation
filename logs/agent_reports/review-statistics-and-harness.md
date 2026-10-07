## Verdict per claim
- **K1: SURVIVES.** Same boot, interleaved: CPU 0 8/95 vs CPU 4 0/95, Fisher p=0.0067. With steady runs, CPU 0 had 15 failures in ~285 s, CPU 4 none in ~282 s (p=3e-5). CPU 4 could still fail at 3.1% per import; 20 other CPUs got only 15 imports each.
- **K2: SURVIVES.** The import is single-threaded (my control: `Threads: 1`) with a fixed hash seed, so software has no source for a 6%, one-CPU failure. Pid 27451's impossible fault checks out.
- **K3: WEAKENED.** The direction holds; "only" and "removes" do not. 0/200 still allows 1.5% per import, and only 5.40 and ~5.67 GHz were tested.
- **K4: WEAKENED.** The one record comes from the induced reset, after CPU 0 had been fully busy for ~45 s, so (inference) no C1 exit on that core. The spontaneous resets have no record; `journal-timeline.md:12` puts the busy thread on P-core 4 before reset #1.
- **K5: WEAKENED.** Board power delivery and socket are a third candidate no test touched. A firmware update discriminates only if CPU 0 still reaches 57x at unchanged requested voltage.
- **K6: SURVIVES** for RAM, GPU, driver, OS, PyTorch. PSU is asserted, not tested.
- **K7: WEAKENED.** 54x came from loading neighbours, not a BIOS cap. `taskset -c 1-23` leaves kernel and services on CPU 0; `unattended-upgrade` ran at both spontaneous resets (`journal-timeline.md:7`).

## Strongest objection
K3 rests on a non-randomised design. 150 of the 200 imports at 5.4 GHz ran as one block (14:38:02–14:40:49). The 98 consecutive 5.7 GHz imports around those blocks (14:36:12–14:42:47) were also clean (P=0.003 at 5.74%), and a clean run of 81 followed later; two such runs have P=0.008 at a constant rate. Failures are bursty, so Fisher's p=4e-4 (12/200 vs 0/200) overstates: against a bursty null fitted to the 5.7 GHz gaps, p≈0.003–0.008. The strictly interleaved part alone (4/100 vs 0/50) gives p=0.30.

## Errors or overstatements found
- `max_temp_c` is the Wi-Fi card: `core_probe.py:328` reads `thermal_zone4`, type `iwlwifi_1`; `x86_pkg_temp` is zone 5. No run has thermal data.
- "All fault lines name CPU 0" is false twice, both benign: `boot_20261007_132308_kernel.log:1236` names CPU 22, a deliberate `ctypes.string_at(0)` (`/var/log/apport.log:6`); `boot_20261007_123826_kernel.log:1658` is `nvidia-smi` on CPU 15, after oops #1.
- `20261007_140229_spawn.tsv` (600 spawns in 3 s) is not the torch import; rows omit `--code`. Rightly excluded, undocumented.
- `boot_20261007_140952_kernel.log` stops at 14:21; the 13 later fault lines are only in the journal.

## Evidence I verified myself
Recount, matching the investigator's:

| Torch import | Failed | 95% CI | Avg MHz |
|---|---|---|---|
| CPU 0 alone | 13/220 | 3.2–9.9% | 5647–5676 |
| CPU 0 kept awake | 2/50 | 0.5–13.7% | 5623–5652 |
| CPU 0, E-cores 8+12 busy | 12/200 | 3.1–10.3% | 5656–5679 |
| CPU 0, P-cores 2+3 busy | 0/200 | 0–1.8% | 5390–5398 |
| CPU 4 | 0/95 | 0–3.8% | 5656–5680 |
| Others | 0/490 | 0–0.75% | 4600–5492 |

- **Rate consistency:** 0.055 failures/s from spawns predicts 2.8 in 50 s of steady (2 occurred) and 0.35 in CPU 0's ~6.3 s of burst compute, so the clean burst proves nothing.
- **Harness:** no CPU 0 asymmetry; children pinned by `taskset`, supervisor on CPU 23.
- **Telemetry:** `scaling_cur_freq` escapes the mis-scaling (cpu3: 5,444,164 kHz against `cpuinfo_max_freq` 4,000,000) but is one ~1 ms sample per spawn.
- **CPU 0 is not IRQ-special:** 10.4% of interrupts; the nvidia IRQ sits on CPU 16.
- **Pages are not CPU-private:** per-CPU list limit 1357 pages; each import frees 277 MB.
- **One mechanism:** 16 of 27 failures at 5.7 GHz are the same event: 10 crashes at `python3.11+0x218228`, 6 identical `TypeError: __traceback__ must be a traceback or None`.
- **Not checked:** voltages, BERT, MCE decoding.

## Tests that would settle what is still open
Rootless:
1. Randomised blocks of 25 on CPU 0: alone, `--load-cpus 2` (stays 57x), `--load-cpus 2,3`, `--load-cpus 8,12`; 300 per arm, logging per-spawn MHz and `x86_pkg_temp`. Can reset the machine.
2. 300 imports on CPU 4; 95 on each of CPUs 2, 5, 6, 7.

Root:
3. Cap CPU 0 alone at 54x, 55x, 56x through its HWP request, without neighbour load.
4. Install rasdaemon so every reset keeps its record.
5. Around the firmware update, record CPU 0's frequency and MSR 0x198; require 0/600 imports.
6. Try the CPU in another board before an RMA.

Scripts: `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/`
