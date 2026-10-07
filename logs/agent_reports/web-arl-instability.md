## 0. Scope and limits
- Web research plus a few light read-only local reads (sysfs, dpkg, journalctl) on 2026-10-07 13:29–13:42 CEST. No sudo, no GPU/NVIDIA access, no stress or loops. None of my commands crashed or was signalled.
- Scratch files are in `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/webresearch/`: `specupdate_834774.pdf` and `specupdate.txt` (Intel spec update rev 023), `releasenote.md` (Intel microcode release notes), `hochschild.pdf`, `dixit.pdf`, `fmb.txt`, and kernel sources `intel_pstate_v6.14.c`, `intel_idle_v6.17.c`, `bert_v6.14.c`.
- Sources I could not open:
  - HTTP 403: community.intel.com, forum-en.msi.com, msi.com (support page, API, blog), rog-forum.asus.com, phoronix.com, igorslab.de, older Intel spec-update revisions.
  - HTTP 402 paywall: overclock.net, videocardz.com.
  - Body truncated: tomshardware.com and techradar.com articles.
  - Anything from these is marked "search summary only".

## 1. Observed facts (local)
- **Firmware is stale.** `dpkg -l intel-microcode` shows 3.20250512.0ubuntu0.24.04.1 installed; `apt-cache policy` shows candidate 3.20260210.0ubuntu0.24.04.1. Running microcode is 0x118; BIOS is 1.A70 dated 04/27/2025.
- **CPU 0 and CPU 4 are the two favored cores.** `acpi_cppc/highest_perf` is 66 on CPU 0 and 4, 64 on the other P-cores, 46 on all E-cores. `scaling_cur_freq` on cpu0 read 5706777 kHz while only my shell was running, so CPU 0 does run at 5.7 GHz under light load.
- **cpufreq numbers are inconsistent in the known way.** P-cores: `nominal_perf`=59, `nominal_freq`=3700, `cpuinfo_max_freq` 4.0–4.1 GHz. E-cores 8–15 and 18–23: `nominal_perf`=44, `nominal_freq`=3200, max 3.3 GHz. CPU 16–17: `nominal_perf`=32, max 4.6 GHz. Driver is intel_pstate active, governor powersave, EPP performance.
- **Deep C-states are in heavy use.** cpuidle driver is intel_idle with ACPI-derived states: `C1_ACPI` (MWAIT 0x0), `C2_ACPI` (MWAIT 0x21), `C3_ACPI` (MWAIT 0x60). Nine minutes after boot, cpu0 had spent 493 s in `C3_ACPI`.
- **Power limits are within Intel spec.** RAPL (MSR): long_term 200 W, short_term 250 W; MMIO peak_power 425 W. Thermal throttle counters on cpu0 are all 0.
- **All relevant knobs are root-only.** `/dev/cpu_dma_latency`, `/dev/mcelog`, `/dev/cpu/0/msr` are `crw------- root`; cpuidle `disable`, `no_turbo`, `max_perf_pct`, `scaling_max_freq` are root-writable only. `perf_event_paranoid`=4.
- **No MCE consumer is installed.** `rasdaemon`, `mcelog`, `stress-ng` and `gcc` are absent; `taskset`, `localedef`, `python3`, `xz`, `zstd`, `openssl`, `turbostat` and `cpupower` are present.
- **MCE/BERT lines per boot** (`journalctl -k -b N | grep -iE 'mce:|BERT'`):
  - Boots −4 and −1 have both "mce: [Hardware Error]: Machine check events logged" and "BERT: [Hardware Error]: Skipped 1 error records".
  - Boot 0 has BERT only.
  - Boots −6, −5, −3, −2 have neither line.
- **The first MCE reset followed an OCCT run.** Boot −5 (2026-10-06 11:29:34 → 12:35:26) contains 80 OCCTGUI journal lines (PID 3729, 11:30:48 to 11:34:58). `DEBUG_REPORT.md` §4.7 lists an OCCT Memory 1 h run "finished ~12:35". The journal's last lines are rtkit at 12:34:58, "Lockdown: systemd-logind: hibernation is restricted" at 12:35:22 and systemd-hostnamed at 12:35:26, then it stops with no shutdown sequence.
- **The second MCE reset was during light desktop use.** Boot −2 (12:32:53 → 12:36:31) ends while udisks was mounting a Ventoy loop image.

Inferences from these:
- The 2026-10-06 reset happened within about a minute of a one-hour all-core load ending, with the user at the desktop. That is a load-to-idle transition, not steady idle. Run #9's oops (teardown after timeout) is the same kind of moment.
- MWAIT hints 0x21 and 0x60 correspond to core C6 and C10, so the "other cores entering C6 or deeper" precondition of the errata below is met constantly.
- The power limits rule out an "MSI Unlimited" (4096 W) preset. They say nothing about Lite Load, AC loadline or CEP.

## 2. Web findings by task item

### Item 3a — Intel errata for the 285K (primary source, strongest find)
Intel "Core Ultra Processors (Series 2) Specification Update", doc 834774 rev 023, September 2026, column "S/S Plus 8+16". Fetched from https://cdrdv2.intel.com/v1/dl/getContent/834774; HTML mirror at https://edc.intel.com/content/www/us/en/design/products/platforms/details/arrow-lake-s/core-ultra-200s-series-processors-specification-update/errata-details/.

| Erratum | First published | Status (285K) | Text |
|---|---|---|---|
| ARL036 | rev 008, May 2025 | Fixed | "a core may encounter incorrect data when other cores in the system are entering Core C6 or deeper sleep states… unpredictable system behavior"; Intel adds it was only seen in a synthetic test environment |
| ARL037 | rev 008, May 2025 | **Planned Fix** (still unfixed) | Two or more cores in a module entering or exiting C6+: cores "may hang without a Machine Check Error being logged" |
| ARL047 | rev 010, July 2025 | Fixed | "an indirect branch may jump to a different location than the location expected and reported, leading to the execution of incorrect instructions" |
| ARL050 | rev 011, Sept 2025 | Fixed | "System Hang or… Internal Timer Machine Check Exception (IA32_MCi_STATUS.MCACOD=400h and… MSCOD=E1C4h) Following a Core C1 Exit" |
| ARL054 | rev 012, Oct 2025 | Fixed | REP SCASB/CMPSB may return incorrect results |
| ARL033 | rev 006, March 2025 | Fixed | Consecutive RDTSC may return the same value during a frequency increase |
| ARL028 | rev 005, Feb 2025 | No Fix | L1 cache errors are reported as L2 in IA32_MC1_STATUS (matters when decoding an MCE) |

- Workaround text for all the "Fixed" ones is "It may be possible for the BIOS to contain a workaround". The document does not name a microcode version.
- All four key errata were published after this board's BIOS (2025-04-27).
- Arrow Lake-S microcode history from Intel's release notes (https://github.com/intel/Intel-Linux-Processor-Microcode-Data-Files/releases): 0x118 (20250512) → 0x119 (20250812) → 0x11a (20251111) → 0x11b (20260210) → 0x121 (20260512) → 0x122 (20260811). This machine is five releases behind.
- Latest BIOS for this board is 7E54v1AE0, 2026-08-03, per https://flashmyboard.com/mb/MSI_PRO_Z890-S_WIFI. That site is third-party and labels its changelog summary "AI-synthesized"; it mentions later BIOSes carrying 0x11A (MR4) and 0x121. I could not verify against MSI.
- Inference, unverified: ARL047 and ARL050 fixes most plausibly arrived in 0x119 or later; ARL036 could be in 0x118 or later.
- Unverified: I do not know whether an OS-loaded microcode applies every fix a BIOS update would. One Meteor Lake case shows OS-loading a newer revision than the BIOS can itself misbehave: 0x2a via initrd caused instant reboot until the BIOS was updated (https://github.com/intel/Intel-Linux-Processor-Microcode-Data-Files/issues/112). That report does not involve Arrow Lake.

### Item 3b — Linux reports on 285K/265K
- **Defective 285K on Linux (Michael Stapelberg).**
  - First CPU: lockups, xHCI dying, a hard crash under a Django test suite, "crash every time when building a Linux kernel", and Prime95 errors "within seconds". It persisted across two boards (ASUS PRIME Z890-P, ASRock Z890 Pro-A), a PSU swap and a GPU swap; MemTest86 was clean. RMA fixed it.
  - Second CPU died in July 2025 after a 4 h, ~300 W, ~100 °C job. He reports shop reviews "many of which (!) mention CPU replacements".
  - Sources: https://michael.stapelberg.ch/posts/2025-03-19-intel-core-ultra-9-285k-on-asus-z890-not-stable/, https://michael.stapelberg.ch/posts/2025-05-15-my-2025-high-end-linux-pc/, https://michael.stapelberg.ch/posts/2025-09-07-bye-intel-hi-amd-9950x3d/
  - His first CPU failed Prime95 at once, a grosser defect than here. Note that this machine has never run Prime95, y-cruncher or a per-core test.
- **Segfaults at DDR5-8000 on ASUS BIOS 0805, fixed by 0806** (Phoronix, https://www.phoronix.com/review/intel-arrow-lake-ddr5; search summary only). Not applicable at JEDEC 4800.
- **No report found** of a Linux Arrow Lake kernel bug producing random user-space segfaults, or of a decoded "Machine check events logged" on a 285K.
- **Kernel facts for decoding (not Arrow Lake-specific).**
  - `bert.c` v6.14 skips any record of 1024 bytes or more (`ACPI_BERT_PRINT_MAX_LEN 1024`), so "Skipped 1" means one oversize record. My guess is an Intel CrashLog record; unverified.
  - The boot-time "mce:" line means a valid MCi_STATUS survived the reset (my reading of the kernel's MCE code; not checked against source in this session). Nothing consumed the details because no rasdaemon or mcelog is installed.

### Item 3c — cpufreq and idle quirks: known and cosmetic
- **cpuinfo_max_freq is misreported by design plus firmware.** Mainline v6.14 and v6.17 have no Arrow Lake entry in `intel_hybrid_scaling_factor[]` (verified in source). The entry was dropped by the patch "Drop Arrow Lake from 'scaling factor' list" (https://lkml.iu.edu/hypermail/linux/kernel/2412.0/06582.html). The kernel therefore computes frequency as `nominal_freq/nominal_perf` from firmware CPPC. That reproduces this machine's numbers exactly: 3700/59 × 66 ≈ 4.1 GHz; 3200/44 × 46 ≈ 3.3 GHz; 3200/32 × 46 = 4.6 GHz.
- **Same symptom reported upstream.** Aaron Rainbolt on a 275HX: P-core max "3.9 GHz" against a 5.4 GHz spec on 6.14.6, while measured frequencies were correct. Srinivas Pandruvada (Intel): "the BIOS didn't program frequencies correctly in ACPI CPPC". Unresolved as of December 2025. https://lists.snapcraft.io/archives/kernel-team/2025-May/159710.html, https://ratatoskr.run/linux-acpi/2025/05/8989252/t
- **The CPU 16–17 oddity is known.** Russell Haley on a 265K (ASRock and MSI boards): "two of the E-cores report 33 for nominal_perf, while the others report 46". https://lkml.iu.edu/hypermail/linux/kernel/2505.0/00579.html
- **Conclusion:** this is a reporting bug, not a cause. HWP still runs the cores at true frequency.
- **intel_idle has no native Arrow Lake table** in v6.17 (verified) and uses ACPI _CST. This contradicts an Unraid forum claim that support was "added in 6.13" (https://forums.unraid.net/topic/197400-intel_idle-not-registering-native-c-states-on-intel-core-ultra-200-series-arrow-lake-model-0xc6/).

### Item 2 — C-states, Speed Shift, TVB, DLVR
- **285K freezes cured by disabling C-states** (Intel community thread; search summary only, board and BIOS unknown): CLOCK_WATCHDOG_TIMEOUT, DRIVER_POWER_STATE_FAILURE and freezes without BSOD, stable after disabling CPU C-states. https://community.intel.com/t5/Mobile-and-Desktop-Processors/Intel-Core-Ultra-9-285K-Complete-system-freezes-related-to-CPU-C/td-p/1755415
- **Arrow Lake-H laptop (285H) idle freezes on Linux, fine on Windows**, with no kernel log. Workarounds were `intel_idle.max_cstate=2` or `pcie_aspm=off`. https://discussion.fedoraproject.org/t/random-freeze-on-idle-sleep-thinkpad-t14p-2025-intel-ultra-9-285h-arc-pro-integrated-gpu/183627
- Both are hangs, not data corruption or segfaults.
- **Speed Shift:** only ARL035 (HWP_STATUS cleared after PC10 exit, fixed). No instability reports found.
- **TVB:** stock behaviour drops one bin when two or more P-cores are active above 70 °C (SkatterBencher). No Arrow Lake TVB crash reports found. The Raptor Lake eTVB bug is a precedent only.
- **DLVR:** each P-core and E-cluster has an on-die regulator fed from VccIA. "Power Gate" bypass has not been user-selectable since microcode 0x112 (Tom's Hardware headline; search summary). DLVR bypass is therefore not a candidate at stock.

### Item 1 — MSI Lite Load, AC/DC loadline, CEP
- **Z790 precedent, MSI blog** (search summary only): "Intel Default" in CPU Lite Load Control restores Intel voltage behaviour and "may result in an increase in the processor's voltage". "Normal" mode: start at Mode 15 and step down to the lowest stable mode. "Advanced" allows a manual AC loadline. https://www.msi.com/blog/improving-gaming-stability-for-intel-core-i9-13900k-and-core-i9-14900k
- **CEP:** MSI recommended disabling it on non-K 14th-gen parts. With CEP enabled and a reduced AC loadline, performance dropped up to 40% (Tom's Hardware via Yahoo, 2024-03-08, https://tech.yahoo.com/computing/articles/msi-details-intel-cpu-run-190148635.html). A search summary of forum-en.msi.com thread 400984 says "IA CEP is disabled by default on Z-series boards"; unverified.
- **Z890:** boards must ship with the Intel Default Profile as default (https://tech.yahoo.com/computing/articles/intel-z890-motherboards-reportedly-ship-174443890.html). MSI offers four presets: Intel Default, MSI Performance, Extreme, Unlimited (search summary).
- **Not found:** any Z890 report that MSI's default Lite Load undervolts Arrow Lake into idle or light-load instability. The mode-to-milliohm tables are on overclock.net, which is paywalled.
- **Caution on interpretation:** a 13900K on an MSI Z790 that was only stable at a changed Lite Load mode with turbo disabled was judged a degraded CPU (https://forums.tomshardware.com/threads/msi-lite-load-control-%E2%80%93-intel-13900k-stability-performance-issues-any-suggestions.3878440/). "Stable with more voltage or less turbo" does not separate a board undervolt from a marginal CPU.

### Item 4 — Defective-core precedent and why all-core stress passes
- **Stock 285K turbo table:** "57X when up to 2 P-cores are active, 54X when 3 or more". The V/F curve reaches about 1.31–1.385 V at 5.7 GHz, against about 1.12 V at about 5.2 GHz under all-core AVX2 (two different samples). https://skatterbencher.com/2025/03/16/skatterbencher-84-core-ultra-9-285k-overclocked-to-5800-mhz/, https://skatterbencher.com/2024/10/24/arrow-lake-p-core-overclocking/
- **Inference:** the 8 h `stress-ng`, OCCT and MemTest86 "all CPUs" runs never exercised the 5.5–5.7 GHz points. Only CPU 0 and 4 reach them, and only when two or fewer P-cores are active.
- **CoreCycler README** states the same mechanism: all-core tests miss single-core instability because "the cores cannot boost as high". It is Windows-only. https://github.com/sp00n/corecycler
- **Google, "Cores that don't count":** "typically just one core fails, often consistently"; failures "non-deterministically at variable rate"; f, V and T all matter and "lower frequency sometimes (surprisingly) increases the failure rate". Symptoms include "process and kernel crashes" and machine-check logs. Rate is "a few mercurial cores per several thousand machines". https://sigops.org/s/conferences/hotos/2021/papers/hotos21-s01-hochschild.pdf
- **Meta, "Silent Data Corruptions at Scale":** a defect reproducible only when pinned to one core ("Core 59"). https://arxiv.org/abs/2102.11245
- **AMD Ryzen 2017:** gcc segfaults with ECC and memtest-clean RAM. https://lkml.iu.edu/hypermail/linux/kernel/1707.3/02309.html
- **Raptor Lake Vmin shift:** Intel says Arrow Lake is unaffected (search summary: techspot, pcgamesn).
- **Linux per-core tools:** OCCT's core-cycling CPU test, mprime (Prime95) or y-cruncher under `taskset`, Intel's OpenDCDiag (https://github.com/opendcdiag/opendcdiag, build from source).

### Item 5 — RTX 4090 / 12VHPWR / PSU
- No report found of GPU or PSU transients causing segfaults in CPU-only processes with the GPU idle.
- Documented PSU and transient symptoms are freezes, reboots, shutdowns and Xid 79 (https://seasonic.com/insights/gpu-and-psu-failure-symptoms/, https://www.netdata.cloud/guides/nvidia-gpu/nvidia-gpu-xid-79-fallen-off-bus/).
- The only idle-specific PSU precedent is the Haswell C6/C7 minimum-load issue (0.05 A on 12V2; https://pcper.com/2013/05/possible-power-supply-issues-for-intel-haswell-cpus/). The PSU model is not recorded in the repo.

## 3. Ranked candidates
Ranking is my judgement. Reasons for 1 over 2: the crash rate here is far above anything reported fleet-wide on 0x117/0x118, and Intel says ARL036/037 were seen only synthetically.

**1. Marginal or defective P-core at the top turbo points (CPU 0 most suspect).**
- Mechanism: one core mis-executes at 5.5–5.7 GHz, a point reached only at light load.
- Fit: strong.
  - Crashes at light load and process start.
  - CPU 0 is named in the localedef ×2, python3.11 and oops events.
  - CPU 0 was observed at 5.7 GHz.
  - The oops fault address (CR2) does not match the faulting instruction's operand (rbp−8), which bad RAM cannot produce.
  - All-core tests never reach these points.
  - The MCE resets came at load release or light use.
- Weakness: CPU 0 would be named under any light-load hypothesis, because it is a favored core.
- Rootless test: a single-thread reproducer pinned per CPU, described in section 4.
  - Only CPU 0 fails → defective core.
  - CPU 0 and 4 fail, others clean → top-bin marginality.
  - All cores fail similarly → not this candidate.
- Fix: RMA the CPU. Interim: keep work off CPU 0 with `taskset` or cpuset, or cap the P-core ratio at 54x in BIOS.

**2. Stale firmware missing the errata fixes (ARL036, ARL047, ARL050; ARL037 still open).**
- Mechanism: section 2, item 3a.
- Fit: good. Deep C-states are in constant use, the pattern is light-load or transition, and ARL050 matches "MCE then reset near idle". The oops at teardown, when many threads go idle together, fits ARL036.
- Weakness: frequency, as above.
- Test (needs root or BIOS): measure the reproducer's crash rate, then update, then re-measure.
  - Quick: `apt install intel-microcode` gives 0x11b.
  - Full: BIOS 7E54v1AE0 plus ME firmware.
  - Decode the next MCE: MCACOD=0x0400 with MSCOD=0xE1C4 would confirm ARL050.
- Caveat: newer microcode may also change voltage behaviour, so "fixed after update" does not fully exclude candidate 1.
- Do this first regardless. It is cheap and Intel and MSI will require it before an RMA.

**3. Board voltage configuration (Lite Load, AC loadline, CEP).**
- Mechanism: too little voltage at the high-frequency points.
- Fit: same pattern as candidate 1, but no Z890 evidence was found, and the power limits look Intel-spec.
- Test: read the BIOS OC page (Performance Preset, CPU Lite Load Control and mode, AC/DC loadline, IA CEP). With root, `turbostat` shows core voltage.
- Fix: Intel Default Settings with Lite Load at "Intel Default" and CEP enabled, or raise the mode by 1–2 steps. If it then needs above-spec voltage to be stable, treat as candidate 1.

**4. C-state or idle platform problem outside microcode (BIOS C-state config, PSU low-load, VRM).**
- Fit: matches the idle resets and community hang reports. Weak for segfaults.
- Test (root): disable `C2_ACPI` and `C3_ACPI` via sysfs `disable`, or boot with `intel_idle.max_cstate=1 processor.max_cstate=1`, or set a BIOS package C-state limit.
- Confound, from Intel's legacy turbo definition and unverified on Arrow Lake: cores idling in C1 count as active, so this also removes the 57x bin. Pair it with a `no_turbo=1` run, which keeps C6 but removes the high bins, to separate the two.

**5. Intermittent memory, slot or memory controller.** Low. MemTest86 ×4, OCCT Memory ×2 and memtester all passed at JEDEC speed, and the oops signature is not a RAM signature. A decoded MCE bank would settle it.

**6. PSU, 12VHPWR or GPU transients.** Low. Crashes occur with the GPU idle; `gpu-burn` 8 h and OCCT Combined (432 W GPU) passed. The only test is a PSU swap.

**7. Kernel or driver bug, including the cpufreq and CPPC quirks.** Not causal. The quirks are cosmetic, the fault spans three kernels and three NVIDIA drivers and hits CPU-only processes, and an MCE is hardware-detected.

## 4. Suggested test sequence
I ran none of these; they need scheduling around the other pinned experiments.

1. **Rootless per-core baseline.**
   - Reproducer: `taskset -c N localedef -i de_DE -f UTF-8 <scratch>/de_DE.UTF-8`, or `CUDA_VISIBLE_DEVICES="" taskset -c N <pixi python> -c "import torch, torchvision"`.
   - Run a few hundred iterations each for N = 0, 4, 1, 2, 3, 5, 6, 7 and one E-core.
   - Log the exit code, time, and `scaling_cur_freq` of CPU N.
   - Check once with `strace` that the import does not open `/dev/nvidia*`.
2. **Rootless top-bin discriminator.**
   - Repeat the CPU 0 run while two `nice` busy loops are pinned to CPUs 2 and 3.
   - That makes three active P-cores, which should cap CPU 0 at 54x; confirm via `scaling_cur_freq` ≤ ~5.4 GHz.
   - Other cores still cycle through C6.
   - Crashes vanish → top-bin V/F problem (candidates 1 or 3). Crashes persist → candidates 2 or 4.
3. **With root, one change at a time:**
   - Install `rasdaemon`, and after each reset save `/sys/firmware/acpi/tables/data/BERT` and pstore.
   - `no_turbo=1` run.
   - C2/C3 disable run.
   - Microcode 0x11b.
   - Photograph the BIOS settings, then update the BIOS.
4. **If CPU 0 is still implicated after the BIOS update:** RMA the CPU, with Stapelberg's case as precedent.

## 5. Not determined
- Which microcode revision fixes which erratum.
- MSI's actual BIOS changelogs after 1.A70.
- This board's Lite Load mode, AC/DC loadline and CEP state.
- The content of the MCE and BERT records.
- Whether ITMT is enabled (the sysctl is not exposed on 6.14).
- The PSU model.
- Whether the two MCE-boot resets were spontaneous or user-pressed after a hang.
