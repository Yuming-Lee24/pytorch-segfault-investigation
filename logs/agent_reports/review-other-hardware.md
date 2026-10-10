## Verdict per claim
- K1: SURVIVES, narrowed. CPU 0 at 27/470 against 0/585 elsewhere is solid. CPU 4's clean exposure is only about 280 s (95 spawns + 2×90 s), which bounds its rate at roughly 5× below CPU 0's, not at zero.
- K2: SURVIVES. Confirmed on core 27451 in gdb. It excludes RAM, storage and software, not voltage or temperature as upstream causes.
- K3: WEAKENED. 54x was reached only by loading P-cores 2+3, which also changes CPU 0's voltage, package current and the shared rail. 55x and 56x are untested.
- K4: WEAKENED. The one decoded record (CPU 0, bank 3) stands. The other two resets are extrapolation: the OCCT screenshot of 12:35:26, about a minute before reset #1, shows CPU 4 at 100 % / 5648 MHz and CPU 0 at 800 MHz / 8 %.
- K5: WEAKENED. It omits board-level voltage (BIOS settings, VRM). A BIOS update also resets settings, so neither outcome separates board from CPU.
- K6: WEAKENED. RAM, storage, GPU/driver, PyTorch and OS/kernel survive. PSU, board VRM and core temperature were never tested directly.
- K7: WEAKENED. `taskset -c 1-23` leaves kernel and desktop work on CPU 0 (2.6 % busy during the current GPU test). Only the 54x cap is supported.

## Strongest objection
Frequency was never varied alone, and CPU 4 is not a like-for-like control. Decoding `logs/rootdiag/*/perf_status_samples.tsv` (bits 47:32 / 8192; encoding unvalidated on Arrow Lake), CPU 0 is requested 1.319 V at x57 (n=2) and 1.316–1.321 V at x51–52 (n=21). CPU 4 gets 1.361 V at x57 (n=1) and 1.329–1.331 V at x52 (n=4). At x54 CPU 0 has the lowest range, 1.216–1.221 V (others up to 1.261 V). The results fit "CPU 0's top-bin voltage is too low on this board" (fused curve, firmware, or board loadline/VRM) as well as "core 0 is defective". The report does not mention it.

By alternative:
- (a) RAM: excluded. Per-CPU page reuse is possible (pcp `high_max` 83,083 pages; 77,570 faults per import), but identical pinning gave 0/200 at 54x.
- (b) PSU/VRM: not excluded. Against it: CPU 4 clean, all-core runs pass.
- (c) Socket: untested; contact faults should worsen at all-core current.
- (d) Thermal: unmeasured. Against it: loading 2+3 heats the package yet gave 0/200.
- (e) Storage: excluded (below).
- (f) Kernel/BSP: excluded. Only IRQ 0 (24 counts) and one iwlwifi queue (1) are CPU 0-only; microcode is 0x118 on 24/24 CPUs; turbostat SMI is 0 in both idle captures.

## Errors or overstatements found
- `scripts/core_probe.py:328` reads `thermal_zone4`, which is `iwlwifi_1` (`x86_pkg_temp` is zone 5). Every `max_temp_c` (47–48) in `logs/core_probe/*.tsv` is the Wi-Fi card, and both `turbostat.txt` captures are idle (max CoreTmp 40 and 38 °C). No CPU temperature exists for any failing run.
- "All fault lines that name a CPU name CPU 0": `logs/kernel/boot_20261007_132308_kernel.log:1236` names CPU 22. `/var/log/apport.log` shows a deliberate `ctypes.string_at(0)`: harmless, but unstated.
- `msr.tsv` 0x19c bit 13 (current-limit log) is set on all CPUs in both captures; never decoded.

## Evidence I verified myself
- TSV totals reproduce exactly: 13/220, 2/50, 12/200, 0/200, 0/95, 0/490.
- gdb on core 27451, in place: `si_addr` 0x415; `rax+0x60` is in writable `.PyRuntime` and still holds the pre-store value, equal to xmm1.
- `mcelog.bin` bytes: status 0xbe000000e1c40400, CPU 0, bank 3.
- SHA-256 of installed files against conda-meta, read on CPUs 6–7: only 130 `.pyc` differ, all structurally identical to fresh compiles (`bin/python3.11` is prefix-rewritten, so skipped).
- Reproducer on CPU 5: 0 major faults, no `/dev/nvidia*` opens.
- Live: thermal-throttle counters 0; CPU 4 reaches 72–76 °C at 5.7 GHz.
- The OCCT screenshot in K4, viewed directly.

## Tests that would settle what is still open
Rootless (1–3 pin CPU 0 and can reset the machine):
1. `--cpus 0 --load-cpus 4`: both favoured cores at 57x, rail set by CPU 4's higher request. Failures vanish: rail headroom. Persist: the core or its V/F point.
2. `--cpus 0 --load-cpus 8-23`: 57x at high package power. Persist: VRM light-load and PSU low-load are out.
3. Fix the temperature source; compare coretemp "Core 0" with "Core 24" under equal load.
4. At least 1,000 spawns and 15 min steady on CPU 4.

Root or BIOS:
5. `scaling_max_freq` on policy0 at 5.4, 5.5, 5.6 GHz, nothing else loaded.
6. MSR 0x34 (SMI count) around a failing run; turbostat during it.
7. Record Lite Load, loadline and CEP before any BIOS update; then +50 mV on P-core 0 alone.
8. The CPU in another board.
