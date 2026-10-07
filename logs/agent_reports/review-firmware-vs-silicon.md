Verdict per claim
K1: SURVIVES. Recomputed from /home/yuming/pytorch-segfault-investigation/logs/core_probe/*.tsv: CPU 0 at 5.62-5.68 GHz 27/470; CPU 4 at 5.66-5.68 GHz 0/95 (P≈0.4% at CPU 0's rate) plus 2x90 s steady clean. Other CPUs: mostly 15 runs.
K2: SURVIVES against RAM/storage/software. ARL047's wording ("different location than ... expected and reported") means impossible-looking fault state does not alone exclude an erratum.
K3: WEAKENED. The only clean condition (CPUs 2+3 busy) changes ratio and P-core sleep behaviour together; the other-cores-busy control used E-cores only. 175 of the 200 clean runs fall in 14:37-14:41, bracketed by 75 clean runs at 5.7 GHz (P≈1.2%), so failures cluster in time and "1 in 100,000" is overstated.
K4: WEAKENED. One reset is proven (mcelog.decoded.txt: cpu 0, bank 3, 0xbe000000e1c40400); the two earlier resets have no record. The ARL050 link rests on the code pair alone.
K5: WEAKENED. Silicon (a) is better supported than firmware (b), and a firmware update is not a clean discriminator.
K6: SURVIVES; not attacked.
K7: WEAKENED. The 54x cap is supported; taskset -c 1-23 leaves kernel, interrupts and other processes on CPU 0.

Strongest objection
ARL050 needs "following a Core C1 exit". The captured machine check came 45 s into steady mode, a sleep-free CPU-bound loop pinned to CPU 0 (/home/yuming/pytorch-segfault-investigation/scripts/core_probe.py lines 262-266), so CPU 0 was not leaving C1. MC3 ADDR and MISC hold 0x00005b9d2564a239, a user-space address in python3.11's mapping range (0x58e2...-0x64bc...), not a kernel idle path. Design errata exist in all eight identical P-cores, and none in rev 023 is conditioned on ratio, voltage or a particular core, yet CPU 4 is clean at 57x. The voltage data shows a per-core, top-bin-only difference: at x57 CPU 0 requests 1.3187 V (2 samples; 25 of 100 samples at 1.316-1.324 V, never higher) against 1.3613 V for CPU 4 (1 sample), 43 mV less, while at x54 they agree (1.216-1.221 V vs 1.221-1.229 V). P-core V/F points are factory-fused per core (SkatterBencher). That points to core 0's top V/F point lacking margin: an RMA matter. Caveats: tiny sample; the 0x198 voltage field under DLVR and the ADDR meaning are undocumented.

Errors or overstatements found
- /home/yuming/pytorch-segfault-investigation/DEBUG_REPORT.md line 364 says Intel maps no microcode revision to errata; Red Hat/Oracle microcode_ctl notes tie 0x119→0x11a to ARL054, so ARL050's fix is plausibly in 0x119-0x11b.
- The report never analyses /home/yuming/pytorch-segfault-investigation/logs/rootdiag/20261007_143159/perf_status_samples.tsv.
- "Discriminating step": a cure cannot separate an erratum fix from raised voltage masking a weak core; persistence cannot separate silicon from unfixed errata (ARL037 "Planned Fix", ARL068 "No Fix"). OS-loaded 0x11b leaves BIOS reference code and ME 19.0.5.1948 untouched.
- Counter-precedent: Intel Community thread 1757603 (Core Ultra 9 285): BIOS plus microcode 0x11b→0x121 did not stop MCE cold resets; its CrashLog reason codes (0x44, 0x20003, 0x10) match this machine's, though they may be generic.
- 1.3187 V is not out of range (SkatterBencher's 285K: 1.313 V fused at 5.7 GHz, limit 1.513 V). A Lite Load undervolt singling out one core at single-core current is unlikely.
- Flash risk is understated: no Flash BIOS Button (MSI specification page); MemTest86 shows the boot CPU only at 37x and 54x.

Evidence I verified myself
- TSV totals, frequencies, timestamps; core_probe.py; both rootdiag captures; scripts/decode_bert.py output. I ran nothing on CPU 0.
- Intel 834774 rev 023: E1C4h appears only in ARL050; ARL068 names "THREE STRIKE (E184H)".
- Intel errata pages: LNL046 repeats ARL050's text; MTL046 places three-strike in MC3_STATUS.
- Lunar Lake LKML report (July 2026): bank 3 0xbe000000e1840400 at cpuidle exit, unresolved.
Not verified: MSI changelogs, BIOS microcode contents, whether OS-loaded microcode updates pCode, Stapelberg's RMA.

Tests that would settle what is still open
Rootless:
1. CPU 0 imports with one P-core busy (still 57x), interleaved in blocks of 25 with the 2+3 condition.
2. CPU 4: 300+ imports, longer steady runs.
3. Read the BIOS screen: preset, CPU Lite Load mode, IA CEP.
Root:
4. Sample MSR 0x198 2,000+ times for CPUs 0 and 4; repeat after every firmware change.
5. Cap only CPU 0 to 54x (policy0 scaling_max_freq), other cores idle; conversely 57x with C2/C3 disabled.
6. Microcode 0x11b, then BIOS flashed with P-cores capped at 54x first. If CPU 0 still fails, or only a +40 mV core-0 offset cures it, RMA.
