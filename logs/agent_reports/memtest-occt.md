**Stress-artefact extraction: MemTest86 log + 4 OCCT screenshots (with light cross-checks from live sysfs and the journal)**

Sources:
- `MT` = `/home/yuming/pytorch-segfault-investigation/0510-test-result/memtest86/MemTest86-20261006-115028_603727.log` (cited as `MT:line`; timestamps UTC, CEST = UTC+2).
- `S1`–`S4` = `/home/yuming/pytorch-segfault-investigation/0510-test-result/occt-screenshot/` `OCCT-26105-051319.png`, `OCCT-26105-051330.png`, `OCCT-26106-123526.png`, `OCCT-26106-013836.png`. Native-resolution crops I read from are in `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/stress-artefacts/`.
- Cross-checks (read-only, not stress artefacts): `/proc/cpuinfo`, `/sys/class/hwmon`, `/sys/class/powercap`, cpufreq sysfs, `journalctl`, `/home/yuming/pytorch-segfault-investigation/logs/kernel/*.log`.

None of my commands crashed or received a signal. Repo untouched.

**Note on boot indices:** `journalctl --list-boots` shows −6…0, which differs from the task text. The boot that ended abruptly at 2026-10-06 12:35:26 is **−5**; the first MCE boot (10-06 12:36:56) is **−4**.

---

## A) MemTest86 — OBSERVED FACTS

### System, CPU, clocks

| Item | Value | Source |
|---|---|---|
| Tool | MemTest86 V11.7 Free, Build 1000 (64-bit), booted via Ventoy USB | MT:69, MT:51 |
| BIOS (SMBIOS) | AMI, Version "1.A70", Release "04/27/2025"; EFI spec 2.80 | MT:71, MT:75 |
| System / board | MSI "MS-7E54" v1.0; board "PRO Z890-S WIFI (MS-7E54)" v1.0, S/N 07E5412_O91B385850 | MT:72, MT:74 |
| CPU | GenuineIntel Core Ultra 9 285K, Family 0x06, Model 0xC6, Stepping 0x2 | MT:239, MT:334-337 |
| Microcode revision | **Not logged** (no MSR 0x8B, no "microcode" string in the file) | grep of MT |
| Caches | L1d 48 KB/12-way, L1i 64 KB, L2 3072 KB, L3 36864 KB | MT:241-244 |
| Logical CPUs | 24 present, 24 enabled, 0 hyperthreads, 1 package, BSP = Proc 0 | MT:502-558 |
| **CPUs actually used** | **16 of 24**: "The number of cores (24) is greater than the maximum supported (16). Limiting the number of cores to 16." | MT:557, MT:683 |
| MP dispatch test | AP#1–#15 started; CPU #1–#15 all "finished execution"; "MP test passed. Setting default CPU mode to PARALLEL" | MT:562-594 |
| CPU selection mode | 1 (parallel) | MT:1418 |
| MSR 0xCE | 08040838F1812500: max non-turbo ratio 37, min ratio 8, min operating ratio 4 | MT:340 |
| MSR 0x1A2 | 0000000000691400: TjMax 105 °C, TCC offset 0, bits 15:8 = 20 | MT:341 |
| MSR 0x1AD (turbo limits) | 3636363636363939: 57, 57, 54, 54, 54, 54, 54, 54 | MT:342 |
| MSR 0x1A0 | 0x850089 as found: turbo enabled (bit 38 = 0), EIST on, TM1 on. MemTest86 set bit 38 briefly, then restored it | MT:344-345, MT:367-368 |
| MSR 0x199 | 0x3900: "Target multiplier: 57, Max1CTurbo: 57" | MT:370 |
| MSR 0x198 on BSP | 00001E5900002500 at 37x; 0000272800003600 and 0000273D00003600 at 54x ("Current multiplier: 54") | MT:352, MT:369, MT:377 |
| MemTest86 "CPU speed" | 3750.1 MHz; "Freq: 3750135KHz (Ratio: 3700, ExtClk: 101355KHz), Turbo: 5473170KHz (Ratio: 5400) (Theoretical max: 5777235KHz)" | MT:314, MT:388 |
| BCLK register | 147 polls, 0x18689…0x186B1 = 99.977–100.017 MHz, mode 100.000 | MT:1469 and following |
| Bench | L1 657324 MB/s, L2 142405, L3 42919, RAM 25842 MB/s, latency 27.762 ns | MT:317-332 |
| CPU temperature | 269 samples (about 1 per 61 s): **min 44 °C, max 62 °C**. Hottest in Test 8 (62 °C) and Test 7 (60 °C); Hammer test 44–48 °C | grep "Current CPU temperature" |
| DIMM temperature | DIMM0 32.25–44.50 °C, DIMM1 32.25–44.75 °C | grep "DIMMn temperature" |

### Memory controller and DIMMs

| Item | Value | Source |
|---|---|---|
| Controller | Intel Arrow Lake 8086:7D1A; DDR5; 2 MCs × 2 channels, each with one 16 GiB 2-rank x8 DIMM-L (34359738368 B per MC) | MT:596-680 |
| ECC | CAPID0_A=02002118 "ECC capable: no"; "IBECC disable: yes"; ECC polling disabled; SMBIOS MemoryErrorCorrection 3 | MT:601, MT:604, MT:680-684, MT:1342 |
| Configured timings | 4800 MT/s (polled 4798–4800), **40-39-39-77**, gear_mode=0, QCLK_RATIO=72. Identical in all 1084 polls for the whole run | MT:1458-1470 |
| SMBIOS configured | Speed 4800, ConfiguredMemoryClockSpeed 4800, Min/Max/ConfiguredVoltage **1100 mV** (both DIMMs) | MT:1361, MT:1379 |
| Slots | 4 slots, max 128 GB. **DIMMA2** (BANK 0) S/N 881C7D8C; **DIMMB2** (BANK 1) S/N 861C79EF; DIMMA1 and DIMMB1 empty | MT:1342-1381 |
| Both DIMMs (identical SPD apart from serial) | Kingston **KF560C30-32**, DDR5 UDIMM 32768 MB, 2 ranks x8, non-ECC, **Year 2024 Week 39**, location 0x01; DRAM SK Hynix stepping 0x41; SPD5118 hub; one PMIC5100 (vendor 8A8C); no TS5111 sensors; Raw Card B Rev 0 | MT:837-886, MT:1088-1137 |
| JEDEC profile | 1.1 V VDD/VDDQ, 1.8 V VPP; tCKmin 0.416 ns (4800 MT/s); tAA/tRCD/tRP 16.000 ns; tRAS 32 ns, i.e. 40-39-39-77 | MT:845-859 |
| XMP 3.0 Profile 1 "Profile 1 Ultra" | certified; tCK 0.333 ns (DDR5-6000); tAA 9.990 / tRCD 11.988 / tRP 11.988 / tRAS 26.640 ns (30-36-36-80); **VDD/VDDQ 1.4 V**, VPP 1.8 V | MT:902-931 |
| XMP Profile 2 "Profile 2 Ultra" | tCK 0.357 ns (DDR5-5600); 14.28/14.28/14.28/28.56 ns (40-40-40-80); **1.25 V** | MT:932-961 |
| XMP Profile 3 / 4 / 5 | 3 not enabled; 4 "Rewritable Profile 4" user slot with nonsense values (VDD 2.35 V, tCK 40.961); 5 empty user slot | MT:962-971 |
| EXPO 1.1 | Profile 1 = 6000, 9.990/11.988/11.988/26.640 ns, 1.4 V; Profile 2 nonsense values | MT:972-1006 |
| Memory map | 99 entries; TOLUD 0x80000000, TOM 0x1000000000, TOUUD 0x1080000000; total 68183949312 B; available 62 GB, reserved 1343 MB; no "unusable/bad" region types | MT:396-500, MT:605-608 |

### Test session

- **Session:** 11:51:04 → "Test result: PASS (Errors: 0)" at 16:24:23 UTC, i.e. 13:51:04 → 18:24:23 CEST (MT:1417, MT:6586).
- **Passes:** 4, each ending "Cumulative error count: 0, buffer full count: 0" (MT:2392, 3796, 5181, 6583). Wall time 45:34, 75:52, 75:58, 75:52.
- **Tests run:** 0–10 and 13 only. Tests 11 and 12 never appear; the log gives no reason. Nothing was aborted.

Per-test durations as logged (tool seconds, pass 1 / 2 / 3 / 4):

| Test | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| T0 walking ones, 1 CPU | 1.228 | 1.228 | 1.228 | 1.227 |
| T1 own address, 1 CPU | 8.017 | 8.183 | 8.192 | 8.493 |
| T2 own address | 6.419 | 6.722 | 6.334 | 6.394 |
| T3 moving inversions 1s/0s | 25.059 | 56.403 | 56.385 | 56.513 |
| T4 8-bit pattern | 94.189 | 222.565 | 222.329 | 223.249 |
| T5 random pattern | 100.056 | 296.786 | 295.946 | 295.364 |
| T6 block move | 75.280 | 213.178 | 213.266 | 213.155 |
| T7 32-bit pattern | 371.597 | 882.036 | 881.636 | 881.293 |
| T8 random number sequence | 56.399 | 163.052 | 163.007 | 162.936 |
| T9 modulo 20 | 244.741 | 728.001 | 727.996 | 728.206 |
| T10 bit fade, 1 CPU | 620.940 | 621.010 | 620.697 | 621.069 |
| T13 hammer | 1083.677 | 1274.500 | 1282.091 | 1275.502 |

Other session facts:
- **Hammer test used 4 CPUs only:** all 124 lines read "Running hammer test on 4 CPUs (512MB each)" (e.g. MT:6563).
- **Warning/error scan:** no CPU timeout, no "unresponsive", no retry (SPD read "[Attempt 0]" succeeded, MT:770). The only hits are benign: "Length of SPD (256) not valid" ×2 on the first probe (MT:735), no network protocol (MT:65-66), "iMS support is NOT available" (MT:219), font glyph warnings, ECC unavailable.
- **Idle after the test:** the next line after PASS is "2026-10-07 10:30:42 - Display test result summary" (MT:6587); the log ends 10:31:06 UTC = 12:31:06 CEST (MT:6606). The same session sat at the result screen about 18 h 06 min without resetting.
- **MemTest86's clock is 1.7 % fast:** its own elapsed-ms counters advance at 0.98297× the RTC timestamps over 15098 s (my calculation from the 48 "Start time: N ms" lines).

### MemTest86 — INFERENCES

- **Which CPUs were never tested.** Mapping APIC IDs (MT:507-553) to `/proc/cpuinfo`: the 16 used are Linux cpu0–5 (P), cpu8–15 (E), cpu16–17 (E). **cpu6 and cpu7 (P) and cpu18–23 (E) ran no MemTest86 test.** CPU 0 is the BSP, so it was used. I assume the single-CPU tests ran on the BSP; the log does not say.
- **The 3750 MHz / "ExtClk 101355 kHz" figures are a calibration artefact, not a BCLK overclock.** MemTest86 timed the TSC against HPET and got 3750.15 MHz. Linux enumerates "tsc: Detected 3686.400 MHz TSC" (`boot_20261007_123826_kernel.log:72`), and NTP is locked at +35.8 ppm on the tsc clocksource. 3686.4/3750.15 = 0.98300 matches the 0.98297 drift above. The BCLK register reads 100.00 MHz.
- **Real frequencies on the BSP:** rescaling the APERF/MPERF ratios (MT:355, MT:380) gives 3701 MHz with turbo off and **5402 MHz (54x)** with turbo on.
- **Pass 1 is shorter** because it ran reduced iterations (T3–T9 about 2.3–3× quicker; T10 unchanged). The durations are stable across passes 2–4, so there is no sign of throttling or stalls.
- **MSR 0x198 voltage field**, if it is the usual 1/8192 V VID encoding on this CPU: 0.948 V at 37x, **1.224–1.226 V at 54x** on the BSP. I could not validate that encoding for Arrow Lake.
- The "Memory controller Voltage Level: 3.0V" lines and the XMP-4 / EXPO-2 values are decoder artefacts.

---

## B) OCCT screenshots — OBSERVED FACTS

**Common to all four:**
- Title bar "OCCT PERSONAL 17.1.6", Monitoring tab; columns Value / Min / Avg / Max.
- **It is the Linux build.** Sensor groups are Linux hwmon names (`coretemp` "Package id 0", `iwlwifi_1`, `spd5118`, `r8169_0_8200:00`, `acpi_fan`, `acpitz`); the journal shows `OCCTGUI[3729]` (Avalonia) and "OCCT[2882]: sh: 1: ipmi-sensors: not found".
- Right panel: 01:00:00 / 01:00:00, "No errors detected", five green steps (Schedule Started → … Initializing → Started → Stopped → Schedule Completed).
- GPU Power Limit tile: 450.00 W.

| | S1 + S2 (same run; S2 scrolled down) | S3 | S4 |
|---|---|---|---|
| File mtime (CEST) | 10-05 17:13:23 / 17:13:32 | 10-06 12:35:29.1 | 10-06 13:38:43 |
| Test | **Combined** | **Memory** | **Memory** |
| Header: CPU | 43.0 °C, 1.66 %, 4544 MHz (S2: 2.32 %, 800 MHz) | **62.0 °C**, 5.60 %, 800 MHz | 38.0 °C, 0.271 %, 666 MHz |
| Header: Memory | 7 %, 4891 MB (S2: 4910 MB) | 4 %, 2858 MB | 2 %, 1619 MB |
| Header: GPU | 40.0 °C, 25.9 W, 7 % (S2: 31.5 W, 4 %) | 38.0 °C, **60.7 W**, 2 %, 2550 MHz | 38.0 °C, 33.7 W, 0 % |
| Package id 0 (Val/Min/Avg/Max °C) | 43 / 36 / 64.99 / **91** | 62 / 34 / 63.72 / **80** | 38 / 38 / 58.84 / **68** |
| CPU Usage (Val/Min/Avg/Max %) | 1.66 / 0.08 / **63.70** / 100 | 5.60 / 0.08 / **92.35** / 100 | 0.27 / 0.10 / **33.51** / **89.18** |
| Per-core usage averages | all 63.2–66.6 % | all 92.1–92.9 % | P 63.9–80.1 %; E falls from 33.1 % (E-core 8) to 1.1 % (E-core 23) |

**Core temperature maxima, rows in OCCT order ("P-core 0…7", "E-core 8…23"), °C:**
- Combined: 82, 78, 74, 74, 74, 74, 74, 74, 74, 74, **92**, 84, 88, 84, 84, 84, 84, 84, 78, 76, 78, 76, **92**, 90. Minimums 32–36; averages 55.4–62.8.
- S3: 64, 62, 64, 64, 64, 64, 64, 64, 64, 64, 70, 68, 76, **80**, 68, 68, 68, 68, 68, 68, 66, 66, 72, **80**. Minimums 30–32. Current value of row "E-core 12" = **62 °C**.
- S4: 64, 62, 62, 62, 62, 62, 64, 64, 62, 62, **68**, 66, **68**, 66, 66, 66, 64, 64, 62, 62, 62, 62, 66, 66.

**Core clocks, "Core N Clock" (MHz):**

| | Combined (S1) | Memory 1 (S3) | Memory 2 (S4) |
|---|---|---|---|
| Core 0 (Val/Min/Avg/Max) | 4544.11 / **400.07** / 3845.18 / **5700.00** | 800.00 / **400.14** / 5078.38 / **5700.00** | 665.58 / **431.51** / 4500.36 / **5700.06** |
| Core 4 max | **5700.00** | **5699.94** (value at capture **5648.03**) | **5700.06** |
| Cores 1, 2, 3, 5, 6, 7 max | 5500.06, 5500.00, 5500.00, 5500.06, 5490.53, 5500.00 | 5507.18, 5463.33, 5500.00, 5408.19, 5400.11, 5500.11 | 5500.00–5500.06 |
| Cores 1–7 avg | 3713–3849 | 5057–5088 | 3763–4534 |
| Cores 8–23 max | 4603.81–4659.00, plus Core 12 = **4709.90** | 4602.15–4679.41 | 4610.10–4664.73 |
| Cores 8–23 avg | 3241–3303 | 4327–4399 | 1317–2562 |
| Minimums | 800.00 everywhere except Core 0 and Core 17 (784.86) | 800.00 except Core 0 | 800.00 except Core 0 |

- At S3 capture, "P-core 4 Usage" = **100.00 %**; every other core was 0–8 %.

**S2 — lower part of the list (Combined run only), Val / Min / Avg / Max:**
- GPU Temperature 40 / 39 / 47.13 / **67 °C**
- GPU Power 31.47 / 17.78 / **99.82** / **432.14 W**
- GPU Power Limit 450 W throughout
- GPU Usage 4 / 0 / **27.31** / 99 %
- VRAM 1533.50 / 1051.06 / 2429.34 / 14513.19 MB (max 59.08 %)
- SM and Graphics Clock max 2685 MHz; Memory Clock max 10501 MHz; Video Clock max 2070 MHz
- Physical memory load 4910 / 4416 / 37759.54 / **57986 MB**; available min 5682 MB; usage max 91 %
- spd5118 temp1: 44.75 / 32.75 / 45.48 / **53.75 °C** and 44.00 / 31.75 / 44.85 / **53.00 °C**
- iwlwifi_1 48–62 °C; r8169 40–62 °C
- Lexar SSD NM790 4TB: Composite 49.85–61.85 °C, Sensor 2 36.85–52.85 °C
- acpitz temp1: constant 27.80 °C
- **acpi_fan fan1: 0 / 0 / 0 / 0 RPM**

**Graph tiles (S3):** Core 0 clock near 5.4 GHz for about three quarters of the window, then low; GPU power flat near 14 W with a sharp spike to 60.66 W at the right edge; memory load just above the 50000 MB gridline, then dropping to 2858 MB.

**Not visible in any screenshot** (S2 is the only one showing the bottom of the list, and it has no such rows):
- any CPU voltage (Vcore, VID, VCCSA, VDD2, measured DRAM voltage), so **minimum Vcore and voltage droop cannot be read**;
- CPU package power and power limits;
- +12 V / +5 V / +3.3 V rails;
- real fan speeds;
- WHEA/MCE or any error counter (only the "No errors detected" banner);
- OCCT test settings (threads, memory %, Combined composition).

For S3 and S4 the GPU, memory and DIMM-temperature rows are scrolled out of view.

Supporting sysfs fact: the only hwmon devices on this machine are acpi_fan, acpitz, r8169, nvme, spd5118 ×2, coretemp and iwlwifi_1. No Super-I/O driver is loaded, which is why OCCT has no voltages or fans.

### OCCT — INFERENCES

- **OCCT's "P-core / E-core" temperature labels are positional and wrong.** The rows follow coretemp core-id order (0, 4, 8–15, 16, 20, 24, 28, 32–39, 40, 44, per `/sys/class/hwmon/hwmon6/temp*_label`). So rows 0, 1, 10, 11, 12, 13, 22, 23 are the eight P-cores (Linux cpu0–7 in that order) and rows 2–9 and 14–21 are E-cores. S3 corroborates this: row 12 reads 62 °C while cpu4 is at 100 % and 5648 MHz.
  - Corrected P-core maxima, Combined run: cpu0 82, cpu1 78, cpu2 92, cpu3 84, cpu4 88, cpu5 84, cpu6 92, cpu7 90 °C.
  - The "Core N Clock" and "Usage" rows do use Linux CPU numbers.
- **Only cpu0 and cpu4 ever reach 57x (5.70 GHz).** The other P-cores top out at 5.5 GHz. This matches live `acpi_cppc/highest_perf` = 66 for cpu0 and cpu4, 64 for cpu1–3 and cpu5–7. cpu0 is the core named in the crash logs.
- **Under all-core load the P-cores ran at about 5.4 GHz and the E-cores at about 4.6 GHz.** Memory run 1 averaged 5.07 / 4.34 GHz at 92 % duty. All four passing stress tests therefore validated at most 54x; 55–57x occurs only in light or bursty load.
- **The Combined run was not a sustained simultaneous full load.** Average CPU usage was 63.7 %, GPU usage 27.3 %, GPU power 99.8 W (432 W is the peak), memory load 37.8 GB. Journal lines suggest the test ran about 16:12 → 17:12. The start of the statistics window is unknown (possibly 16:04), but under either assumption the GPU was near full load for only about 17–19 minutes. This weakens the report's §4.7 claim that the Combined run counts against a power-delivery problem.
- **Memory run 2 was a much lighter CPU load than run 1** (33.5 % vs 92.35 % average; E-cores barely used; package max 68 vs 80 °C). OCCT was launched at 12:37, so the statistics window is essentially the test itself. Cause not determinable; it should not count as a repeat of run 1.
- **The first MCE hard reset happened within about 1.5 minutes of the 1-hour all-core load ending.** Evidence from boot −5:
  - the last OCCT GUI line before the test is at 11:34:58, and an rtkit line appears at 12:34:58, so the test likely ended about 12:34:58;
  - S3 was captured at 12:35:26 and written at 12:35:29.1 (intact PNG);
  - the journal's last entry is 12:35:26.43, with no shutdown sequence;
  - the next boot (−4, 12:36:56) logs "mce: [Hardware Error]: Machine check events logged".
  
  At capture the machine was near idle, with one favoured P-core (cpu4) at 100 % / 5648 MHz and the package at 62 °C. journald may have lost up to tens of seconds, so the reset falls roughly between 12:35:30 and 12:36:30.
- **The second MCE reset followed the same pattern.** The machine sat about 18 h in MemTest86's result screen with no reset, then Linux booted at 12:32:53 on 10-07 and died at 12:36:31; the following boot logged the MCE. Both MCE resets occurred at light load under Linux, and none occurred during 7.5 h of sustained testing.
- **Core 0's 400–431 MHz minimum** (below the 800 MHz floor every other core shows) equals the minimum operating ratio of 4 in MSR 0xCE. Whether it is real or a sampling artefact on cpu0 is undetermined.
- **E-core maxima of 4603–4710 MHz** (up to 2.4 % over 4600) are most likely sampling jitter, since BCLK measured 100.00 MHz. That is not proven.

---

## C) Deviations from Intel stock / undervolt / overclock / throttling

| # | Finding | Tag |
|---|---|---|
| 1 | Turbo ratio limits 57/57/54/54/54/54/54/54 (MT:342); max non-turbo 37x; observed maxima 5.70 GHz on P (two cores only) and about 4.6 GHz on E; BCLK 99.98–100.02 MHz | FACT |
| 1a | These match the advertised 5.7 / 4.6 GHz, so there is no core-ratio or BCLK overclock. The intermediate turbo bins and E-core ratio limits cannot be checked from these files | INFERENCE |
| 2 | DDR5 runs at JEDEC 4800 40-39-39-77 with SMBIOS ConfiguredVoltage 1100 mV; XMP (6000 CL30 1.4 V; 5600 CL40 1.25 V) and EXPO exist in SPD but are not applied. The 1100 mV is firmware-reported, not measured | FACT |
| 3 | "Intel 200S Boost" looks inactive, since that profile goes together with an XMP memory profile above 1.1 V. Ring/NGU/D2D fabric ratios are not in either source, so it is not strictly excluded | INFERENCE |
| 4 | No thermal throttling evidence. Peaks: 92 °C core / 91 °C package (Combined), 80 °C and 68 °C (Memory), 62 °C (MemTest86), against TjMax 105 °C (MT:341; coretemp crit = 105000). No "throttl" or "temperature above" kernel lines in boots −6/−5/−4; `thermal_throttle` counters are 0 in the current boot | FACT |
| 4a | 91–92 °C exceeds coretemp's "max" of 85 °C (TjMax − 20), which is a fan-target hint, not the throttle point | INFERENCE |
| 5 | Power limits are not shown in the artefacts. Live sysfs, current boot: `intel-rapl:0` long_term = **200 W** (window 55.97 s), short_term = **250 W**. `intel-rapl-mmio:0` (enabled=0): long_term 250 W, peak_power 425 W | FACT |
| 5a | PL1 = 200 W is below the 250 W stock figure, i.e. more conservative, possibly a board cooler preset. PL2 equals stock | INFERENCE |
| 6 | Undervolt / "CPU Lite Load" status **cannot be determined**: there is no voltage telemetry in OCCT, and the BIOS loadline, Lite Load, IA CEP and C-state settings appear in neither source. The only voltage datum is the unvalidated MSR 0x198 decode (about 1.224 V at 54x, 0.948 V at 37x on the BSP), with no reference V/F curve to compare against | FACT (absence) / INFERENCE (decode) |
| 7 | Stress-test coverage gap: nothing that passed exercised cpu0 or cpu4 at 55–57x. MemTest86 additionally skipped cpu6, cpu7 and cpu18–23, and hammered with only 4 CPUs | FACT (coverage) / INFERENCE (relevance) |
| 8 | DEBUG_REPORT §4.7 says "all CPUs in parallel mode"; actually 16 of 24. It reads the Combined run as CPU and GPU loaded together for an hour "at up to 432 W"; 432 W is the peak, averages are 99.8 W and 27 % GPU usage | FACT |
| 9 | Live cpufreq oddity (current boot): `cpuinfo_max_freq` is 4.0–4.1 GHz for P-cores and 3.3 GHz for 14 of 16 E-cores (cpu16–17 show 4.6 GHz), while `/proc/cpuinfo` simultaneously shows cpu1 at 5169 MHz and E-cores at about 4600 MHz. CPPC `nominal_perf` is 59 (P), 44 (E), 32 (cpu16–17). Governor powersave, EPP "performance" on all CPUs, turbo on | FACT |
| 9a | This looks like a kHz-labelling mis-scale in intel_pstate from firmware-reported CPPC values, not a real frequency cap. EPP=performance means light bursts go straight to the top turbo bins | INFERENCE |

## Values that could not be read

- **BIOS-shipped microcode revision from MemTest86:** not in the log. The only evidence is Linux's "microcode: Updated early from: 0x00000117" / "Current revision: 0x00000118" (`boot_20261007_123826_kernel.log:809-810`).
- **Any measured voltage** (Vcore, VID, VCCSA, VDD2, DRAM VDD/VDDQ), minimum Vcore, and droop behaviour.
- **CPU package power** (min/max) in every run; PL1/PL2/PL4 as they were during the tests.
- **+12 V / +5 V / +3.3 V rails and real fan RPM** (only acpi_fan = 0).
- **WHEA/MCE counters** in OCCT.
- **GPU, memory and DIMM-temperature rows for both Memory runs** (scrolled out of view).
- **OCCT test parameters** and the exact start of its statistics window.
- **Which 4 CPUs ran the Hammer test**, and which CPU ran the single-CPU tests.
- **Why MemTest86 skipped tests 11 and 12.**
- **Meaning of GEAR_TYPE=0 / gear_mode=0**; SA/NGU/D2D/ring ratios.
- **BIOS options:** CPU Lite Load mode, AC/DC loadline, IA CEP, C-states, cooler preset.
- **Exact second of the 10-06 hard reset** (bounded to about 12:35:30–12:36:30 CEST).
