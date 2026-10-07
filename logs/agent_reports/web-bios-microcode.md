# Firmware / microcode status: MSI PRO Z890-S WIFI (MS-7E54) + Core Ultra 9 285K (CPUID C0662h)

## 0. Bottom line
- **BIOS 1.A70 is 8 official releases behind** the latest, 7E54v1AE0 (2026-08-03). It ships microcode 0x117; Intel's current public ARL-S revision is **0x122** (2026-08-11).
- **0x118 is not current.** The running 0x118 is 5 public revisions behind: 0x119, 0x11a, 0x11b, 0x121, 0x122.
- **ME firmware is 19.0.5.1948** (the MR1-era build); ASRock and ASUS now ship 19.0.11.2289.
- **Four CPU errata marked "Fixed" were first published after this BIOS was built**, per Intel's spec update 834774 rev 023 (Sept 2026). Two match the symptom classes: incorrect instruction execution (ARL047) and a hang with Internal Timer MCE after C1 exit (ARL050).
- **Intel does not publish which microcode revision fixes which erratum**, so whether 0x118 already contains any of these fixes is undetermined.
- **Recommendation:** flash 7E54v1AE0, with an optional cheaper first step of upgrading the Ubuntu `intel-microcode` package (gives 0x11b). Details in section 7.

## 1. Observed locally (2026-10-07, about 13:35 CEST, current boot)
| Fact | Value | Source |
|---|---|---|
| BIOS | `1.A70`, date `04/27/2025`, board `PRO Z890-S WIFI (MS-7E54)` | `/sys/class/dmi/id/{bios_version,bios_date,board_name}` |
| Microcode | `Current revision: 0x00000118`, `Updated early from: 0x00000117`; all 24 CPUs at 0x118 | `journalctl -k -b 0`; `/proc/cpuinfo` |
| Microcode package installed | `3.20250512.0ubuntu0.24.04.1` | `dpkg -l intel-microcode` |
| Microcode package available | `3.20260210.0ubuntu0.24.04.1` (noble-updates / noble-security), not installed | `apt-cache policy intel-microcode` |
| ME firmware | `19.0.5.1948` | `/sys/class/mei/mei0/fw_ver` |
| Idle driver and states (cpu0 and cpu8) | `intel_idle`; C1_ACPI = MWAIT 0x0, C2_ACPI = MWAIT 0x21, C3_ACPI = MWAIT 0x60; all enabled | `/sys/devices/system/cpu/cpu{0,8}/cpuidle/state*/{name,desc,disable}` |
| Idle residency, cpu0, 12 min uptime | state3 (0x60) about 649 s, state2 (0x21) about 59 s, C1 about 8.6 s | same, `time` |
| Kernel cmdline | no `dis_ucode_ldr`, no C-state limits | `/proc/cmdline` |

None of my commands crashed or were killed by a signal.

## 2. MSI PRO Z890-S WIFI BIOS releases
Source: https://www.msi.com/Motherboard/PRO-Z890-S-WIFI/support, read through the browser pane (WebFetch got HTTP 403). Changelogs are verbatim. I did not download any BIOS file.

| Version | Release date | Size | MSI changelog | Microcode shipped |
|---|---|---|---|---|
| **7E54v1AE0** | 2026-08-03 | 9.84 MB | Support new model PRO Z890-VC WIFI6E W | not stated; UNVERIFIED (0x122 inferred from 1AD0) |
| 7E54v1AD0 | 2026-07-21 | 9.84 MB | HUDIMM supported; Improved IOMMU setting; Optimize overclocking (OC) settings; Improve memory compatibility | not stated; UNVERIFIED (0x122 inferred, see below) |
| 7E54v1AC0 | 2026-03-25 | 9.84 MB | Optimized memory overclocking adjustment function; Updated security settings | not stated |
| 7E54v1AB1 | 2026-03-11 | 9.84 MB | Support and optimized for the future Intel Core Ultra series CPU; Implemented the anti-cheat mechanism; Optimized for the latest IPPP driver | not stated; UNVERIFIED (0x121 per flashmyboard) |
| 7E54v1AB0 | 2026-03-11 | 9.60 MB | Support new model PRO Z890-VC WIFI6E | not stated |
| 7E54v1AA0 | 2026-01-12 | 9.62 MB | Improve Memory compatibility; Modify memory OC rule | not stated |
| 7E54v1A90 | 2025-12-09 | 9.62 MB | Improve MultiMonitor support; Modify security setting; **Update MicroCode**; Update GOP | number not stated; UNVERIFIED (0x11B per a search snippet of an X post) |
| 7E54v1A80 | 2025-07-17 | 9.62 MB | Resolve problems with display settings; **Support Intel MR3**; Update GOP | not stated; UNVERIFIED (0x118 or 0x119) |
| **7E54v1A70 (installed)** | 2025-05-19 | 11.30 MB | Update ESA module; Fix beep issue; Support Intel MR1; Support Intel 200S Boost | **0x117 (observed locally)** |
| 7E54v1A64 | 2025-04-22 | 11.30 MB | Support Intel MR1; Support Intel 200S Boost | 0x117 (MR1; ASRock pairs MR1 with 0x117) |
| 7E54v1A61 | 2025-02-13 | 11.04 MB | Improved the reliability for a few non-K CPU SKUs; 4x64GB memory compatibility | UNVERIFIED (0x116 per an igorslab headline) |
| 7E54v1A60 | 2025-01-15 | 11.04 MB | Support Intel PR5; **ME firmware version 19.0.0.1854 updated** | not stated |
| 7E54v1A51 | 2024-12-27 | 11.04 MB | same text as 1A60 | not stated |
| 7E54v1A50 | 2024-12-20 | 11.02 MB | **Update CPU Microcode to 0x114**; Support Intel PR4 | 0x114 |
| 7E54v1A40 | 2024-12-03 | 10.95 MB | Improve system stability; OC solution | not stated |
| 7E54v1A30 | 2024-11-06 | 10.53 MB | Improve memory compatibility; Improve system stability | not stated |
| 7E54v1A21 | 2024-10-28 | 10.53 MB | **Updated Intel CPU uCode 0x112**; fixed dGPU/iGPU conflict; OC solution | 0x112 |
| 7E54v1A20 | 2024-10-04 | 10.11 MB | Fix USB wake issue; Support Live update | not stated |
| 7E54v1A10 | 2024-09-24 | 10.11 MB | New BIOS Release | not stated |

Notes on this table:
- **Keyword check, releases after 1.A70:** "stability" does not appear. "Memory compatibility" appears in 1AA0 and 1AD0. "MicroCode" appears in 1A90 only. "ME firmware" does not appear (the last mention is 1A60). "Intel Default Settings" and "CPU Lite Load" appear in no 7E54 changelog. "200S Boost" appears only in 1A64 and 1A70.
- **MSI states no microcode number after 0x114** on this board. The sibling MAG Z890 TOMAHAWK WIFI page has the same pattern (https://www.msi.com/Motherboard/MAG-Z890-TOMAHAWK-WIFI/support).
- **Beta 1A63** (2025-03-13) is listed only on station-drivers: "Support Intel Maintenance Release 1 (MR1). ME firmware version 19.0.5.1948 updated." This matches the ME version on the machine. https://www.station-drivers.com/index.php/en-us/bios-news/14-msi-bios-drivers/342-intel-z890-serie-800/4422-pro-z890-s-wifi
- **1A90 → 0x11B** rests on a search-result snippet of https://x.com/unikoshardware/status/1999290879874596937 ("msi z890 new bios it comes with the latest microcode 0x11b"). The post itself returned HTTP 402 and is not board-specific.
- **1AD0 → 0x122** is an inference. ASRock's 2026-07-09 BIOS pairs "Intel Microcode 0x122" with "Compatible with one sub-channel DRAM module", which looks like the same Intel drop as MSI's "HUDIMM supported".
- **flashmyboard** (https://flashmyboard.com/mb/MSI_PRO_Z890-S_WIFI) lists 0x117, 0x11A and 0x121 for this board. It is a third-party aggregator and I treat it as UNVERIFIED.
- **Package size** drops from 11.30 MB (1A70) to 9.62 MB (1A80). I could not determine why, or whether later packages still bundle an ME update. MSI's support page for this board has no separate ME firmware download.
- **SHA-256** from the MSI page: 1AE0 `4f7f5fdd36a193ad27986a9a20412164c1cc0e1838ca33a00e3ed6c644ba4a54`; 1AD0 `962ffba59b282edc2994e7aec45262387bf027fac5223b19abb79e6cdd461cb6`.
- **No BIOS flashback:** MSI's spec page lists no "Flash BIOS Button" for this board (https://www.msi.com/Motherboard/PRO-Z890-S-WIFI/Specification).

## 3. Arrow Lake-S microcode history (06-c6-02, platform ID 0x82)
Public Linux releases are from Intel's per-tag pages, `https://github.com/intel/Intel-Linux-Processor-Microcode-Data-Files/releases/tag/microcode-<date>`. Build dates are from the Debian/Ubuntu changelogs (https://changelogs.ubuntu.com/changelogs/pool/main/i/intel-microcode/intel-microcode_3.20260227.1ubuntu1/changelog). The 0x118 row is also confirmed in the local `/usr/share/doc/intel-microcode/`.

| Rev | Build date | Public Linux release | Stated purpose for Core Ultra Series 2 | Seen in vendor BIOS |
|---|---|---|---|---|
| 0x112 | n/a | not released for Linux | n/a | MSI 1A21 (2024-10-28); ASRock Z890 Pro-A 2.17 |
| 0x113 | n/a | not released | n/a | ASRock 2.21 (2024-12-10) |
| 0x114 | n/a | not released | PR4 performance fixes | MSI 1A50 (2024-12-20) |
| 0x115 | n/a | not released | no source found | none found |
| 0x116 | n/a | not released | n/a | ASRock beta 2.22.AS07 (2025-02-19), with ME 19.0.0.1895 |
| 0x117 | n/a | not released | MR1 | ASRock 2.25 (2025-03-26); MSI 1A64/1A70 |
| **0x118 (running)** | 2025-03-20 | microcode-20250512 (first ARL-S entry) | "Update for functional issues" (references doc 834774), plus security advisories | UNVERIFIED |
| 0x119 | 2025-05-14 | microcode-20250812 | functional issues, plus security advisories | UNVERIFIED |
| 0x11a | 2025-06-30 | microcode-20251111 | "Update for functional issues. Refer to Intel Core Ultra Processor (Series 2)"; no security item | ASRock 3.10 (2025-09-10): 0x11A + ME 19.0.5.2018 + MR4 |
| 0x11b | 2025-08-03 | microcode-20260210 | functional issues, plus INTEL-SA-01396 and others | Gigabyte F18 (2025-12-01) per VideoCardz |
| 0x11d | n/a | not released | n/a | ASRock, per VideoCardz/wccftech (Dec 2025) |
| 0x121 | not obtained | microcode-20260512 | functional issues, plus INTEL-SA-01420 | ASRock 3.24 (2026-02-05): 0x121 + ME 19.0.5.2175 |
| **0x122 (current)** | not obtained | microcode-20260811 | functional issues, plus eight INTEL-SA items (01379, 01404, 01423, 01428, 01435, 01441, 01442, 01443) | ASRock 3.31 (2026-07-09): 0x122 + ME 19.0.11.2289 |

- **Later releases do not touch ARL-S:** microcode-20260227 (GNR-D only), 20260812 (removes a Meteor Lake file) and 20260925 (Meteor Lake only).
- **Functional fixes after 0x118: yes.** Every release from 20250812 to 20260811 lists functional updates for Core Ultra Series 2. Intel names no specific erratum per revision.
- **Ubuntu 24.04** carries nothing newer than 3.20260210 (0x11b) for noble (https://launchpad.net/ubuntu/+source/intel-microcode). 0x121 and 0x122 are not packaged there.
- **ASRock source:** https://www.asrock.com/mb/Intel/Z890%20Pro-A/index.asp#BIOS (read through the browser).
- **Press sources:** https://videocardz.com/newz/gigabyte-z890-motherboards-are-now-ready-for-core-ultra-200k-plus-arrow-lake-refresh and https://wccftech.com/gigabyte-confirms-intel-arrow-lake-core-ultra-200s-plus-cpu-support-latest-bios/
- **Caution on OS-loaded microcode:** issue #112 in Intel's repo reports an instant reboot when early-loading new microcode on an older BIOS; it went away once the vendor BIOS contained it. That report is Meteor Lake only, with no Arrow Lake mention. https://github.com/intel/Intel-Linux-Processor-Microcode-Data-Files/issues/112

## 4. Intel spec update errata (document 834774, rev 023, September 2026)
Source: https://cdrdv2-public.intel.com/834774/834774_023.pdf, text-extracted to the scratch file listed in section 9. Line numbers refer to that file. Status is the "S/S Plus 8+16" column, which covers the 285K. Rev 008 (May 2025, https://edc.intel.com/output/DownloadPdfDocument?id=8247) was used for comparison.

| ID | Title | Status | First published | Intel's text (abridged) | Lines |
|---|---|---|---|---|---|
| ARL013 | Unsynchronized Cross-Modifying Code Operations Can Cause Unexpected Instruction Execution Results | No Fix | Oct 2024 | n/a | 533-535 |
| ARL028 | Cache Level Wrongly Reported in Machine Check Banks | No Fix | Feb 2025 | IA32_MC1_STATUS reports level L2 instead of L1; severity is correct | 1412-1424 |
| ARL033 | RDTSC Instructions May Return Non-Incremental Value | Fixed | Mar 2025 | BIOS workaround possible | 1501-1513 |
| **ARL036** | Unpredictable System Behavior May Occur When C6 or Deeper Sleep States Are Used | Fixed (already "Fixed" in rev 008) | May 2025 | "a core may encounter incorrect data when other cores in the system are entering Core C6 or deeper sleep states"; seen only in synthetic tests | 1550-1575 |
| **ARL037** | A Core May Hang When Entering or Exiting C6 or Deeper Sleep States | **Planned Fix (still unfixed in Sept 2026)** | May 2025 | cores in a module entering or exiting C6 together "may hang without a Machine Check Error being logged"; synthetic only | 1580-1592 |
| ARL042 | Power State Package C6 Exit May Hang With Bug Check VIDEO_TDR_FAILURE | Fixed | Jul 2025 | incorrect iGFX initialization | 1657-1671 |
| **ARL047** | Indirect Branches May Cause Execution of Incorrect Instructions | Fixed | Jul 2025 (updated Sep 2025) | "an indirect branch may jump to a different location than the location expected and reported, leading to the execution of incorrect instructions ... unpredictable system behavior" | 1752-1764 |
| **ARL050** | System Hang or System Hang With Internal Timer Machine Check Exception (400h) Following a Core C1 Exit | Fixed | Sep 2025 | "execution of instructions on a processor core may be blocked"; MCACOD=400h, MSCOD=E1C4h | 1815-1829 |
| ARL054 | REP SCASB or REP CMPSB Instructions May Return Incorrect Results | Fixed | Oct 2025 | only when another core modifies the memory being scanned | 1893-1905 |
| ARL075 | Execution of IRET in Compatibility Mode May Free Supervisor Shadow Stack Token | Fixed | Aug 2026 | n/a | 815-817 |

- **Workaround text** for every "Fixed" entry above is "It may be possible for the BIOS to contain a workaround for this erratum." No microcode or BIOS version is named.
- **No erratum mentions** #GP or #PF being raised spuriously, or IERR by name. A text search for "microcode" in the errata section returns nothing; only ARL052 mentions pCode versions.
- **Not applicable to the 285K:** ARL041 (C1E-exit hang), ARL043 (unexpected global reset) and ARL049 (hang with MCE on warm reset) are marked N/A for S-series.

## 5. Intel ME / CSME pairing
| Intel release | Microcode | CSME | Source |
|---|---|---|---|
| PR5 (Jan 2025) | 0x114 | 19.0.0.1854 ("1854v2.2") | MSI 1A60 changelog; Intel field update: "Final performance recipe requires ... a BIOS update containing Intel CSME 19.0.0.1854v2.2" (https://cdrdv2-public.intel.com/845102/Intel-Core-Ultra-200S-Field-Update-2.pdf) |
| (Feb 2025 beta) | 0x116 | 19.0.0.1895 | ASRock 2.22.AS07 |
| MR1 | 0x117 | **19.0.5.1948 (this machine)** | station-drivers (MSI beta 1A63); local `fw_ver` |
| MR3 | UNVERIFIED | UNVERIFIED | MSI 1A80 says only "Support Intel MR3" |
| MR4 | 0x11A | 19.0.5.2018 | ASRock 3.10 |
| Arrow Lake Refresh enablement | 0x121 | 19.0.5.2175 | ASRock 3.24 |
| current | 0x122 | 19.0.11.2289 | ASRock 3.31; ASUS PRIME Z890-P BIOS 3401 beta (2026-09-23) and ME Update Tool 19.0.11.2289v0.4_S (2026-08-10) (https://www.asus.com/motherboards-components/motherboards/prime/prime-z890-p/helpdesk_bios?model2Name=PRIME-Z890-P) |

- **Intel's requirement:** "Failing to update the Intel ME alongside the BIOS and Microcode, may result in unexpected platform behavior." (https://www.intel.com/content/www/us/en/support/articles/000100063/processors.html, last reviewed 2024-11-18, names no versions.)
- **Consequence here:** the OS-loaded 0x118 is already running against an ME built for 0x117. Any newer OS-loaded microcode would widen that gap.
- **ASUS's ME note** reads "Intel has identified security issue that could potentially place impacted platform at risk".

## 6. Inferences (not observed)
1. **Symptom match.** ARL047 and ARL036 are the published errata whose implication text matches random user-space segfaults and the oops where CR2 is inconsistent with the faulting instruction's operand. ARL050 matches "reset while lightly loaded, MCE logged at next boot". Intel has not confirmed this link; it would need the decoded MCE (MCACOD 400h / MSCOD E1C4h for ARL050), which is root-only.
2. **Timing.** 0x118 was built on 2025-03-20. ARL047, ARL050 and ARL054 were first published 4 to 7 months later, and 0x119, 0x11a and 0x11b were all built in between. That makes it plausible, not proven, that 0x118 lacks one or more of these fixes.
3. **C-states.** MWAIT hints 0x21 and 0x60 look like C6-class and C10-class by Intel convention. If so, the machine spends most idle time in the states ARL036 and ARL037 concern. ARL037 has no fix on S-series at any firmware level.
4. **Community reports.** Search snippets describe 285K freezes that stop when C-states are disabled (Intel community thread 1755415; UNVERIFIED, blocked by a bot check I did not bypass). A 285HX report shows silent hangs mitigated by disabling C-states, with corrected MCA bank 7 status `0x880000400004008F` persisting (https://github.com/minisforum-docs/MS-02-Ultra/issues/30). That is a different board and BIOS.
5. **Hardware fault not excluded.** Segfaults at step 12 or 13 under load are not obviously idle-related. A firmware update that fails to help is therefore informative: it removes the errata explanation and strengthens the CPU RMA case.

## 7. Recommendation
All steps need the user; nothing here was done.

1. **Optional first step: upgrade the microcode package.** `intel-microcode` 3.20260210.0ubuntu0.24.04.1 early-loads 0x11b, changes one variable, has no brick risk, and is reversible with the `dis_ucode_ldr` boot parameter. If the crash rate changes, a microcode-fixed erratum is implicated. The catch is the ME mismatch from section 5, so treat it as a diagnostic, not the end state.
2. **Flash 7E54v1AE0 (2026-08-03).**
   - It is the newest release MSI lists for this exact board, and by version order it includes the 1A90 microcode update, the 1AA0 and 1AD0 memory-compatibility changes, and Intel MR3 and later.
   - Per section 3 it should carry microcode in the 0x11b to 0x122 range, loaded from reset together with matching Intel reference code. OS loading alone cannot give that.
   - 7E54v1AD0 is the fallback if 1AE0 misbehaves; it is the last release with a substantive changelog.
   - Flashing an intermediate version (1A80, 1A90) has no documented benefit.
3. **Flash risk.** The machine hard-resets spontaneously, and MSI's spec page lists no Flash BIOS Button. A reset during M-FLASH could leave the board unrecoverable without a programmer. Verify the SHA-256 first and flash from the UEFI M-FLASH environment.
4. **After flashing**, settings reset to defaults. Re-check that XMP is off and 200S Boost is off, then record:
   - the `microcode:` lines in `journalctl -k`;
   - `/sys/class/mei/mei0/fw_ver`. If it still reads 19.0.5.1948, the BIOS package did not update the ME, and MSI support should be asked for the matching ME firmware.
5. **Independent experiment: limit C-states** (BIOS C-state limit, or `intel_idle.max_cstate=1`). This tests ARL036/ARL037, and it is the only available mitigation for ARL037. It does not cover ARL050, which is a C1-exit erratum.
6. **If crashes persist** on the latest BIOS with microcode 0x11b or newer and a matching ME, the published-errata explanation is exhausted and the evidence points to a defective CPU or board.

## 8. Could not verify
- The exact microcode and ME version inside each MSI 7E54 BIOS after 1.A70. MSI does not publish them and I did not download or unpack any BIOS.
- Which microcode revision fixes ARL036, ARL047, ARL050, ARL054 or ARL075.
- What 0x115 was, and the build dates of 0x121 and 0x122.
- The Intel microcode number for "MR3".
- Pages that could not be fetched: the Intel community threads (bot check), x.com posts (HTTP 402), overclock.net (paywall redirect), the ROG forum deep page (403), and the ASUS and Gigabyte full BIOS lists (did not render).
- Raw BERT and MCE contents (root-only, not attempted).

## 9. Scratch files
All under `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/fw-research/`; nothing in the repo was touched.
- `834774_023.txt` — spec update rev 023 (Sept 2026)
- `834774_008.txt` — spec update rev 008 (May 2025)
- `845102_field_update.txt` — Intel 200S field update (Jan 2025)

The source PDFs were saved by WebFetch under `/home/yuming/.claude/projects/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/tool-results/` as `webfetch-1791372599272-r8bxoc.pdf` (rev 023), `webfetch-1791372589783-zcia7j.pdf` (rev 008) and `webfetch-1791372713416-4h8q5h.pdf` (field update).
