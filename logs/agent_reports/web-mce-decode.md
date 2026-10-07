## 0. Headline findings

- **OBSERVED:** the current boot (index 0, 13:23:08) has a BERT line but no `mce:` line. `journalctl -k -b N | grep` over all 7 boots shows `mce: [Hardware Error]: Machine check events logged` only in boot -4 (2026-10-06T12:36:56) and boot -1 (2026-10-07T12:38:26).
- **INFERENCE (from v6.14 source):** the decoded records of those boots existed only in the RAM buffer behind `/dev/mcelog` and were lost at the next reset. `cat /dev/mcelog` run now will almost certainly give a 0-byte file. The BERT region now describes the 13:19 hang / 13:23 reset, not the 12:36:31 event.
- **Best remaining lead:** the BERT payload on Intel client is an Intel CrashLog. Intel publishes a decoder (`iclg`, github.com/intel/crashlog) and a public layout for Arrow Lake-S whose "MCA" record holds per-core MCA banks 0–3 {status, addr, misc}; the PMC_RST record holds reset-cause bits. So BERT can carry machine-check detail independent of `/dev/mcelog`.
- **Trap:** Linux zeroes `block_status` of each BERT status block at boot, and the sysfs file is a live view of that memory. A parser that stops at `block_status == 0` sees nothing. `decode_bert.py` and `iclg` both walk by `data_length`.
- None of my commands died with a signal. I ran no sudo, touched no NVIDIA interface, and wrote nothing into the repo.

## (i) Answers 1–3

### 1. Where boot-time leftover MCA records go (v6.14)

Source: `arch/x86/kernel/cpu/mce/core.c` and `dev-mcelog.c`, tag v6.14, read verbatim from raw.githubusercontent.com/torvalds/linux/v6.14/….

- **Logging at CPU init.** `__mcheck_cpu_init_generic()` (core.c:1847) calls `machine_check_poll(MCP_UC | MCP_QUEUE_LOG, all_banks)`. Each valid bank is queued into the gen-pool only, then its `MCi_STATUS` is written to 0 (`clear_it`, core.c ~825). `__mcheck_cpu_init_clear_banks()` zeroes every bank's STATUS again.
  - Consequence: `rdmsr 0x401+4n` after boot can never show the pre-reset error.
- **Flush.** `mcheck_late_init()` (core.c:2971, late_initcall) calls `mce_schedule_work()`, which runs the `x86_mce_decoder_chain`, highest priority first (enum in `asm/mce.h`: CEC 7, EARLY 6, UC 5, EXTLOG 4, NFIT 3, EDAC 2, MCELOG 1, LOWEST 0):
  - `mce_early_notifier` (core.c:587) fires `trace_mce_record()` and `mce_notify_irq()` (core.c:1781), which prints the rate-limited "Machine check events logged".
  - `dev_mce_log` (dev-mcelog.c) copies the 128-byte `struct mce` into `mcelog->entry[]`, sets `finished=1`, zeroes the stored `kflags`, and on non-AMD sets `MCE_HANDLED_MCELOG` (BIT 5) on the live record.
  - `mce_default_notifier` (core.c:637) calls `__print_mce()` only if `mca_cfg.print_all || !kflags`. With `CONFIG_X86_MCELOG_LEGACY=y` (observed in `/boot/config-6.14.0-27-generic`), kflags is never 0 on Intel, so nothing is printed. That is why only the one-line notice appeared.
- **OBSERVED consistency:** in `logs/kernel/boot_20261007_123826_kernel.log` the mce line is line 808, directly before `microcode: Current revision` (809); BERT lines are 860–861. All are late_initcall time.
- **Buffer.**
  - Length is `max(MCE_LOG_MIN_LEN=32, num_online_cpus())`, so 32 entries here.
  - It is a kernel-RAM `struct mce_log_buffer` {signature[12]="MACHINECHECK", len, next, flags, recordlen, entry[]}. The signature is never returned by `read()`.
  - When full, new entries are dropped and flag bit 0 (`MCE_OVERFLOW`) is set.
  - Records stay until read or reset.
- **Read semantics (`mce_chrdev_read`).**
  - Returns `-EINVAL` unless `*off == 0` and `usize >= len * sizeof(struct mce)` (32 × 128 = 4096 bytes).
  - Copies `next` records, then clears the entries and sets `next=0`: a destructive, one-shot read.
  - A too-small read fails without consuming anything.
  - The first read also calls `__mce_read_apei()`, which would return and erase MCE records from ACPI ERST. OBSERVED: this machine has no ERST/HEST/EINJ table (the ACPI list in the kernel log, lines 86–131, has only BERT), so that path returns nothing.
- **Non-root visibility: none** (OBSERVED permissions).
  - `/dev/mcelog` is `crw------- root`.
  - `/sys/kernel/debug` is `drwx------ root`; `debugfs/mce` holds only `fake_panic` and `severities-coverage` (core.c:2959, severity.c:485).
  - Tracefs `events/mce/mce_record/*` and `trace` are `-rw-r----- root`. The event is not enabled at late_initcall unless `trace_event=mce:mce_record` is on the cmdline.
  - `/sys/devices/system/machinecheck/machinecheckN/` exposes configuration only. `bankN` is the CTL mask and returns ENODEV for unimplemented banks (`show_bank`, core.c:2542).
- **INFERENCE:** rasdaemon would also miss these records, because the tracepoint fires before userspace exists. Only `/dev/mcelog` or `mce=print_all` (core.c:2372 `mcheck_enable`) captures boot-time leftovers. The sysfs `print_all` attribute (core.c:2657) is set too late for them.

### 2. `struct mce` layout and ioctls

OBSERVED in `/usr/src/linux-headers-6.14.0-27-generic/arch/x86/include/uapi/asm/mce.h` lines 14–40 (the running kernel's own header). Little-endian, natural alignment, 128 bytes; python `struct` format `"<7Q4BI4B3I4QI4xQ"`.

| off | size | field | off | size | field |
|---|---|---|---|---|---|
| 0 | 8 | status | 66 | 1 | cpu (legacy) |
| 8 | 8 | misc | 67 | 1 | finished |
| 16 | 8 | addr | 68 | 4 | extcpu |
| 24 | 8 | mcgstatus | 72 | 4 | socketid |
| 32 | 8 | ip | 76 | 4 | apicid |
| 40 | 8 | tsc | 80 | 8 | mcgcap |
| 48 | 8 | time | 88 | 8 | synd |
| 56 | 1 | cpuvendor | 96 | 8 | ipid |
| 57 | 1 | inject_flags | 104 | 8 | ppin |
| 58 | 1 | severity | 112 | 4 | microcode |
| 59 | 1 | pad | 116 | 4 | (padding) |
| 60 | 4 | cpuid | 120 | 8 | kflags |
| 64 | 1 | cs | | | |
| 65 | 1 | bank | | | |

- Offsets and size were cross-checked with a `ctypes.Structure` mirror in `--selftest` (no gcc available).
- `read()` returns N × 128 bytes of raw records only.
- ioctls (all need CAP_SYS_ADMIN):
  - `MCE_GET_RECORD_LEN = _IOR('M',1,int) = 0x80044d01`, returns 128.
  - `MCE_GET_LOG_LEN = 0x80044d02`, returns 32 here.
  - `MCE_GETCLEAR_FLAGS = 0x80044d03`, returns and clears the flags (bit 0 = overflow).
- For boot-time leftovers `ip`, `cs` and `tsc` are 0 (`machine_check_poll` passes no regs and no `MCP_TIMESTAMP`), and `time` is the boot-time poll, not the error time.
- `severity` uses `enum severity_level` (`internal.h:12`): 0 NO, 1 DEFERRED/UCNA, 2 KEEP, 3 SOME, 4 AO, 5 UC, 6 AR, 7 PANIC.

**Bank map.**
- OBSERVED (world-readable sysfs `machinecheckN/bankM`): 32 bank files per CPU.
  - P-cores (CPU 0–7) implement banks 0, 1, 2, 3, 4, 6, 7, 8, 9, 14, 16–27.
  - E-cores (CPU 8–23) implement the same set without bank 2.
  - Banks 5, 10–13, 15, 28–31 return ENODEV everywhere.
- Published: Intel's CrashLog collateral for Arrow Lake captures exactly banks 0–3 per core.
- INFERENCE (not published for Lion Cove / Skymont; the SDM has no table for model 0xC6 that I could find): banks 0–3 follow the long-standing Core convention (0 IFU, 1 DCU, 2 DTLB, 3 MLC/L2) and bank 4 is PCU. The missing bank 2 on E-cores fits "DTLB bank on P-cores only". Banks ≥ 6 are unknown.

### 3. BERT on this platform

- **Kernel behaviour** (`drivers/acpi/apei/bert.c` v6.14, `bert_print_all`):
  - Prints a record only if `cper_estatus_len() < ACPI_BERT_PRINT_MAX_LEN (1024)` and fewer than 5 were printed; otherwise it counts it as skipped.
  - It then writes `block_status = 0` for every processed block.
  - `/sys/firmware/acpi/tables/data/BERT` (`drivers/acpi/sysfs.c:415 acpi_data_show`, mode 0400) is a live map of the region; its size is the table's `region_length`. So 44532 bytes is the region size, not the record size.
- **Layout** (OBSERVED in local `include/acpi/actbl1.h:279–293, 1635–1689`, `include/acpi/ghes.h:86–125`, `include/linux/cper.h`):
  - BERT table: 36-byte ACPI header, `u32 region_length`, `u64 address` (48 bytes; the log shows `ACPI: BERT 0x5C2D2000 000030 (v01 INTEL EDK2)`).
  - Status block, 20 bytes: `block_status` (bit0 UC, bit1 CE, bit2 multi-UC, bit3 multi-CE, bits 11:4 entry count), `raw_data_offset`, `raw_data_length`, `data_length`, `error_severity` (0 recoverable, 1 fatal, 2 corrected, 3 none).
  - Data entry: `section_type[16]`, `u32 severity`, `u16 revision`, `u8 validation_bits` (1 FRU id, 2 FRU text, 4 timestamp), `u8 flags`, `u32 error_data_length`, `fru_id[16]`, `fru_text[20]`, plus a BCD `u64 time_stamp` when `revision >> 8 >= 3` (64 or 72 bytes), then the payload.
  - Next block is at `raw_data_offset + raw_data_length` if raw length is non-zero, else `20 + data_length` (`apei-internal.h:124`).
- **Section GUIDs** (`cper.h:177–222`):
  - Processor Generic `9876ccad-47b4-4bdb-b65e-16f193c4f3db`
  - IA32/X64 `dc3ea0b0-a144-4797-b95b-53fa242b6e1d`
  - Platform Memory `a5bc1114-6f64-4ede-b863-3e83ed7c83b1`
  - PCIe `d995e954-bbc1-430f-ad91-b44dcb3c6f35`
  - Firmware Error Record Reference `81212a96-09ed-4996-9471-8d729c8e69ed`
- **IA32/X64 section** (`drivers/firmware/efi/cper-x86.c`): 64-byte header (validation, lapic_id, cpuid[48]); N 64-byte error-info structs (type GUID cache `a55701f5…`, TLB `fc06b535…`, bus `1cf3f8b3…`, MS `48ab7f57…`); M context structs (16-byte header {type, size, msr_addr, mm_addr} plus array, padded to 16; type 1 = MSR dump).
- **Firmware Error Record Reference** (`cper.h:568`, `cper.c:459–510`): {`u8 record_type`, `u8 revision`, 6 reserved, `u64 record_identifier`, GUID}. Type 2 is "SOC Firmware Error Record Type2". Revision 2 means the GUID is valid and the data starts at offset 32.
- **Intel CrashLog GUID** `8f87f311-c998-4d9e-a0c4-6065518c4f6d`:
  - coreboot `src/include/cper.h` (`FW_ERR_RECORD_ID_CRASHLOG_GUID`) and `src/arch/x86/acpi_bert_storage.c` (`bert_append_fw_err`, one FER entry per SRAM region, severity fatal);
  - intel/crashlog `lib/src/cper/section/fer.rs`;
  - a real example in lkml.iu.edu/hypermail/linux/kernel/2011.3/00915.html.
- **INFERENCE:** this board's "1 skipped record" is one status block with one or more FER/CrashLog entries. On a 285HX (same compute-die family, intel/crashlog issue #109) the set was PUNIT, UNCORE, MCA (ARL/CDS), PMC, PMC_RST, PMC_TRACE (MTL/SS) and PMC (MTL/IOEP).
- **CrashLog record format** (intel/crashlog `lib/src/header.rs`, `errata.rs`, `region.rs`):
  - dword0: revision[7:0], header_type[11:8], product_id[23:12], record_type[29:24], cldic[30], consumed[31].
  - Size is (u16@4 + u16@6) dwords.
  - Header types: 0/1 = 8 bytes; 2 adds timestamp u64, agent_version, reason (24 bytes); 3 adds completion status (28); 4/5 are 32 bytes; 6 adds die/socket.
  - A region ends at a version of 0 or 0xDEADBEEF.
  - Record types: 1 PMC, 2 PMC_FW_TRACE, 3 PUNIT, 4 PCORE, 6 ECORE, 8 UNCORE, 0x11 PMC_TRACE, 0x16 TCSS, 0x17 PMC_RST, 0x19 PCODE, 0x1C CRASHLOG_AGENT, 0x3D BOX, 0x3E MCA.
  - Product ids (`target_info.json`): 0x7F ARL/CDS (model 0xC6), 0x98 ARL/CDH, 0x3F MTL/SS, 0x3D MTL/NS, 0x66 MTL/IOEP.
- **Published layouts:**
  - `lib/collateral/ARL/CDS/all/green/crashlog/decode-defs/MCA/1/layout.csv`: 2312 bytes = 8-byte header + 24 cores × banks 0–3 × {status, addr, misc}.
  - `MTL/SS/…/PMC_RST/1/layout.csv` and `MTL/IOEP/…/PMC_RST/1/layout.csv`: `gblrst_req_0`@8, `gblrst_cause_0`@12, `fw_gblrst_cause_0`@16, `host_pr_cause_0`@20 (SS only), `pch_pm_sts2`@24, with bit names such as `cf9`, `sysrst`, `tco_wdt`, `mia_ux_err`, `syspwr_flr`, `pchpwr_flr`, `cpu_thrm_wdt`, `pmc_3strike`, `ocwdt_icc`.
  - The repo gives names only, no descriptions. Reading `sysrst` as the reset button and `cf9` as a port-0xCF9 reset is my inference.
- **Tooling:**
  - Intel `iclg` (commands `extract`, `info`, `triage`, `decode`, `unpack`). On Linux it reads `/sys/firmware/acpi/tables/data/BERT` itself. As a file it accepts `"BERR"` + raw region, or the 48-byte BERT table + region (`lib/src/bert/berr.rs from_bert_file`).
  - The README says platform coverage is limited. Issue #109 reports ARL emitting MCA rev 2 (0x3C2 dwords) with a body entirely 0xDEADBEEF, while only rev 1 is published. Issue #99 confirms the BERR-prefix trick.
  - Intel System Debugger needs an NDA. I found no public "iCAT" or "acdt" decoder for client CrashLog, and I did not verify what fwts' `bert` test covers.
- **PMT (OBSERVED):**
  - `ls -la /sys/class/intel_pmt` shows only `telem1..telem4`, symlinks to `…/0000:00:0a.0/intel_vsec.telemetry.0/intel_pmt/telemN`.
  - Details: telem1 guid 0x1306a0b3 size 3352 offset 744; telem2 0x1a06a001 4608/512; telem3 0x1306a1b3 600/0; telem4 0x1a06a101 136/0. The `telem` files are `-r--r----- root`.
  - `/sys/bus/auxiliary/devices/` holds only `intel_vsec.telemetry.0`; `*crashlog*` does not exist.
  - `pmt_crashlog.ko` exists (alias `auxiliary:intel_vsec.crashlog`) but is not loaded. In v6.14, `pmt/crashlog.c:81–93` accepts only crash type 1 version 0, and `pmc/core_ssram.c:198` registers telemetry only.
  - So BERT is the only OS path to CrashLog here.

## (ii) Review of `scripts/collect_root_diag.sh`

**Correct as written:**
- **L29 `cat /dev/mcelog`** is valid. OBSERVED with `strace cat /etc/hostname`: GNU cat 9.4 issues `read(3, …, 131072)`, well above the 4096 minimum. Output is N × 128 raw bytes; the second read returns 0 and ends cat. A 0-byte file means "no records", not failure. The script's own comment about draining is right.
- **MSR addresses** all match `msr-index.h` of the running kernel: 0x8b, 0xce, 0xe2, 0x179, 0x17a, 0x198, 0x199, 0x19c, 0x1a0, 0x1a2, 0x1ad, 0x1ae (`MSR_TURBO_RATIO_LIMIT1`), 0x1b1, 0x1fc, 0x606, 0x610, 0x64f (`MSR_PERF_LIMIT_REASONS`), 0x770, 0x771, 0x774.
  - None is read-to-clear or write-sensitive.
  - A nonexistent MSR just gives EIO, which the script records as "-". Existence of 0x1ae and 0x64f on ARL is unverified.
  - MSR 0x150 (OC mailbox) is correctly absent and must stay absent: reading it requires writing a command first.
- `rdmsr -0`, decimal register arguments, and the chown block are fine.

**Problems:**
1. L25–26: `2>/dev/null` hides a failed BERT copy.
2. L39: `ls -laR /sys/class/intel_pmt` lists only four symlinks (ls -R does not follow them) and captures no telemetry.
3. L66–81: bank STATUS/ADDR/MISC will be 0 for anything before this boot, because the kernel cleared them. Keep it, but do not expect the old error there.
4. L101: `--quiet` suppresses turbostat's configuration dump (turbo ratio limits, power limits, C-state config), which is the part relevant to voltage and power.
5. Nothing records which boot the capture belongs to, or whether that boot logged the mce line.
6. `dmidecode` and the pstore dumps put serial numbers / UUID into `logs/`. Mind that if the repo is pushed.

**Exact lines.** Also saved, `bash -n` clean, at `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/web-mce-decode/proposed_additions.sh`. Blocks B (minus journalctl), D-ls, F-powercap and H were dry-run without root; the rest could not be run.

```bash
# [A] replace L25-26
cp /sys/firmware/acpi/tables/BERT "$OUT/BERT.table.bin" 2> "$OUT/BERT.err"
cp /sys/firmware/acpi/tables/data/BERT "$OUT/BERT.data.bin" 2>> "$OUT/BERT.err"
cat "$OUT/BERT.table.bin" "$OUT/BERT.data.bin" > "$OUT/BERT.iclg.bert" 2>> "$OUT/BERT.err"
sha256sum "$OUT"/BERT.*.bin > "$OUT/BERT.sha256" 2>> "$OUT/BERT.err"
for t in PHAT FPDT; do cp "/sys/firmware/acpi/tables/$t" "$OUT/$t.table.bin" 2>> "$OUT/BERT.err"; done
# [B] after L29
{ echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"; echo "booted=$(uptime -s)"; echo "cmdline=$(cat /proc/cmdline)"; echo "mcelog_bytes=$(stat -c %s "$OUT/mcelog.bin" 2>/dev/null)"; journalctl -k -b 0 --no-pager -o short-iso | grep -E 'mce:|BERT|Hardware Error|microcode:'; } > "$OUT/boot_context.txt" 2>&1
# [C] after L35
[ -d /sys/fs/pstore ] && cp -r /sys/fs/pstore "$OUT/pstore_sysfs" 2>/dev/null
# [D] replace L39
run intel_pmt_ls.txt ls -la /sys/class/intel_pmt/ /sys/class/intel_pmt/*/ /sys/bus/auxiliary/devices/
for d in /sys/class/intel_pmt/*/; do
    n=$(basename "$d"); mkdir -p "$OUT/intel_pmt/$n"
    for a in guid size offset; do cat "$d$a" > "$OUT/intel_pmt/$n/$a" 2>&1; done
    for b in telem crashlog; do
        [ -e "$d$b" ] && cat "$d$b" > "$OUT/intel_pmt/$n/$b.bin" 2>> "$OUT/intel_pmt/$n/errors.txt"
    done
done
# [E] replace L40
run cpupower_frequency.txt cpupower -c all frequency-info
# [F] after L41
grep . /sys/class/powercap/intel-rapl*/name /sys/class/powercap/intel-rapl*/enabled /sys/class/powercap/intel-rapl*/constraint_* > "$OUT/powercap.txt" 2>&1
grep . /sys/devices/system/cpu/intel_uncore_frequency/*/* > "$OUT/uncore_freq.txt" 2>&1
if [ -d /sys/kernel/debug/pmc_core ]; then
    mkdir -p "$OUT/pmc_core"
    for f in /sys/kernel/debug/pmc_core/*; do
        [ -f "$f" ] && timeout 5 cat "$f" > "$OUT/pmc_core/$(basename "$f")" 2>&1
    done
fi
run lspci_vvv.txt lspci -nnvvv      # optional: PCIe AER/DevSta of root ports and GPU (config space only)
# [G] after L52 (inside the if)
MSRS="$MSRS 0x17:platform_id 0x3a:feature_control 0x10a:arch_capabilities
      0x17b:mcg_ctl 0x4d0:mcg_ext_ctl 0x194:flex_ratio 0x195:overclocking_status
      0x19b:therm_interrupt 0x1a4:misc_feature_control 0x1aa:misc_pwr_mgmt
      0x1b0:energy_perf_bias 0x1b2:pkg_therm_interrupt 0x601:vr_current_config
      0x614:pkg_power_info 0x620:uncore_ratio_limit 0x621:uncore_perf_status
      0x638:pp0_power_limit 0x648:config_tdp_nominal 0x649:config_tdp_level1
      0x64a:config_tdp_level2 0x64b:config_tdp_control 0x64c:turbo_activation_ratio
      0x650:secondary_turbo_ratio_limit 0x690:core_perf_limit_reasons_690
      0x6b0:gfx_perf_limit_reasons 0x6b1:ring_perf_limit_reasons
      0x772:hwp_request_pkg 0x777:hwp_status"
# [G2] L68: add a ctl2 column;  after the "for off" loop on L77:
        printf 'cpu\tbank\tctl\tstatus\taddr\tmisc\tctl2\n'
                printf '\t%s' "$(rdmsr -p "$c" -0 $((0x280 + b)) 2>/dev/null || echo -)"
# [H] after L96: bits 47:32 / 8192 = volts, bits 15:8 = ratio
python3 -c 'import sys
for n, l in enumerate(open(sys.argv[1])):
    f = l.rstrip("\n").split("\t")
    print(l.rstrip("\n") if n == 0 else "\t".join([f[0]] + ["-" if len(x) != 16 else "%.4fV/x%d" % (int(x[4:8], 16) / 8192, int(x[12:14], 16)) for x in f[1:]]))' "$OUT/perf_status_samples.tsv" > "$OUT/perf_status_decoded.tsv"
# [I] after L101
run turbostat_config.txt turbostat --interval 1 --num_iterations 1
```

- Optional replacement for L29 that also records record length, log length and the overflow flag: `python3 /tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/web-mce-decode/capture_mcelog_snippet.py "$OUT"`. It compiles, and without root it fails cleanly with `PermissionError … '/dev/mcelog'`; it is untested as root.

**What is and is not readable about voltage and power limits:**
- PL1/PL2/PL4 are readable without root. OBSERVED now:
  - `intel-rapl:0` long_term 200 W (window 55.97 s, max_power 125 W), short_term 250 W, enabled=1.
  - `intel-rapl-mmio:0` long_term 250 W (enabled=0), peak_power (PL4) 425 W.
  - MSR-RAPL has no PL4 constraint because v6.14 `intel_rapl_msr.c:141–151` `pl4_support_ids` does not list Arrow Lake-S. The raw 0x601 read is the fallback.
- `IA32_PERF_STATUS[47:32]` is the requested VID in 1/8192 V. Its validity with ARL's DLVR is not documented anywhere I found; treat it as indicative only.
- AC/DC loadline, IccMax and CEP status have no read-only MSR or sysfs that I know of. They sit behind the OC/BIOS mailboxes, which need a write. Read them off the BIOS screen.
- Undervolt-protection status should be MSR 0x195 bit 1 (`IA32_OVERCLOCKING_STATUS`). That bit layout is from my memory of SDM Vol. 4, not re-verified this session, and 0x194/0x195 are not in the 6.14 `msr-index.h`.
- intel_pmt telemetry needs XML definitions for the four GUIDs (possibly in github.com/intel/Intel-PMT; not checked).

**Suggestions that change the system (for the human to decide; outside the script's read-only promise; untested):**
- Add `mce=print_all` to `GRUB_CMDLINE_LINUX_DEFAULT` and run `update-grub`. The next boot-time leftover is then printed in full into the journal, with no root tooling needed.
- Add a oneshot systemd unit at boot: `cat /sys/firmware/acpi/tables/BERT /sys/firmware/acpi/tables/data/BERT > /var/log/hwerr/$ts/BERT.iclg.bert; cat /dev/mcelog > /var/log/hwerr/$ts/mcelog.bin`. BERT is overwritten at every boot and mcelog lives in RAM, so a manual run is easy to miss. Once such a unit exists, the manual script will find mcelog empty.

## (iii) `/dev/mcelog` decoder

- Path: `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/web-mce-decode/decode_mcelog.py`
- Usage:
  - `decode_mcelog.py FILE [--pcores 0-7] [--reclen N] [--all]`
  - `--text FILE` parses `mce=print_all` / `__print_mce` journal lines.
  - `--status HEX [--bank N --mcgcap HEX --misc HEX --addr HEX]` decodes one value (for example from CrashLog).
  - `--selftest`.
- Prints every field you listed, plus the UCR class (CE / UCNA / SRAO / SRAR / PCC-fatal), the full SDM compound MCACOD decode, and the bank hint.

## (iv) BERT parser

- Path: `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/web-mce-decode/decode_bert.py`
- Usage: `decode_bert.py FILE [--dump N|--full] [-v] [--extract DIR]`
- Accepts the raw region, the table alone, table + region, or a `BERR`-prefixed file.
- Tolerates the cleared `block_status`; prints every status block and data entry and hexdumps payloads.
- Decodes IA32/X64 sections (check info, MSR context with named `IA32_MCn_*` and decoded STATUS), Processor Generic, Platform Memory, and Firmware Error Record sections.
- For the CrashLog GUID it walks the records and decodes the ARL MCA record (0x7F rev 1, 0x98 rev 2) and PMC_RST rev 1 (0x3F, 0x66). Unpublished MCA revisions get a heuristic scan, labelled as such.
- `--extract` writes `region.berr` (iclg-ready), each payload and each CrashLog record.

**Tests** (synthetic inputs only; full log at `…/web-mce-decode/test_output.txt`, generators `make_test_inputs.py` and `fuzz_test.py`, inputs in `testdata/`):

```
COMPILE_OK
SELFTEST PASSED            (ctypes sizeof==128, 25 offsets, 26 MCACOD cases, 3 status classes, cpuid 0xc0662 -> Arrow Lake-S)
#0 cpu=2 apic=0x10 bank=0 status=0xb200000000000005 UC PCC  mscod=0x0000 mcacod=0x0005 [Internal parity error]
#1 cpu=0 apic=0x0 bank=4 status=0xbe000000e1840400 UC PCC  mscod=0xe184 mcacod=0x0400 [Internal timer error]
#2 cpu=12 apic=0x48 bank=1 status=0x9000004000000135 CE  mscod=0x0000 mcacod=0x0135 [Cache hierarchy error: DRD (data read), D (data) cache, level L1]
#3 cpu=5 apic=0x28 bank=1 status=0xbd80000000100134 UC  mscod=0x0010 mcacod=0x0134 [Cache hierarchy error: DRD (data read), D (data) cache, level L0]
EMPTY FILE: /dev/mcelog held no records when it was read (...)
--- decode_bert.py testdata/bert_region.bin (44532 bytes, block_status deliberately 0)
  block_status    : 0x00000000 ... <-- 0: cleared by Linux bert.c after boot-time processing (or never set); walking by data_length
  status block length (as Linux cper_estatus_len): 6728  -> >= 1024, which is why the kernel printed 'Skipped' instead of the record
  Record Identifier GUID: 8f87f311-c998-4d9e-a0c4-6065518c4f6d  = Intel CrashLog
    [+0x00060] CrashLog record 2: PMC_RST  rev 1  product 0x03f = MTL/SS (meteorlake)
      gblrst_cause_0    = 0x00008000  mia_ux_err(bit15)
      host_pr_cause_0   = 0x00000004  sysrst(bit2)
    [+0x00028] CrashLog record 1: MCA  rev 1  product 0x07f = ARL/CDS (arrowlake, model 0xC6)
      core3  bank3: status=0xbe000000e1840400 addr=0xfffff80252753e75 misc=0x0000000000000086
                    [VAL UC EN MISCV ADDRV PCC] MSCOD=0xe184 MCACOD=0x0400 (Internal timer error)
      MCA banks with VAL=1: 2 of 96
    [+0x00000] CrashLog record 0: MCA  rev 2 ... WARNING: truncated record: declared 3848 bytes, only 3008 available
      body is entirely 0xDEADBEEF: MCA data was NOT collected into this record
      0x00000405 IA32_MC1_STATUS    = 0xbd80000000100134  [VAL UC EN MISCV ADDRV S AR] MSCOD=0x0010 MCACOD=0x0134 (...)
status blocks found: 2; bytes after the last block: 37616 (0 non-zero)
fuzz iterations: 400, exceptions: 0
```

The table+region, `BERR`-prefixed, table-only, all-zero, empty and `--extract` variants also passed (`region.berr` equals `BERR` + region by `cmp`).

## (v) Caveats and uncertainties

1. Neither tool has seen real data. The real `struct mce` layout is certain (the running kernel's header). The real BERT content is inferred from Intel/coreboot/kernel sources and third-party reports; MSI's AMI firmware may differ in entry count, FER revision or record set.
2. The published ARL-S MCA layout is rev 1. A 285HX report shows rev 2 (3848 bytes declared, body 0xDEADBEEF). For rev 2 my parser only scans heuristically and `iclg` may decode headers only. If the body is 0xDEADBEEF, the firmware collected no MCA data.
3. The mapping of CrashLog `coreN` to Linux CPU or APIC id is unpublished. The PMC_RST bit names have no published descriptions. Product 0x3F / 0x66 applying to this Z890 board is inferred from the 285HX report.
4. Which reset types produce a CrashLog/BERT on this board, and whether a reset-button reset preserves `MCi_STATUS`, is not determined. Boot 0 has BERT without mce; boots -4 and -1 have both; boots after clean shutdowns have neither.
5. The bank-to-unit names are convention, not Intel documentation for Lion Cove / Skymont.
6. Not determined: MSR 0x195 bit layout; existence of 0x194, 0x1ae, 0x64f, 0x620/0x621 and 0x690 on ARL; the meaning of 0x601 on ARL-S; validity of the 0x198 voltage field with DLVR. All are read attempts that fall back to "-".
7. Line numbers are given for `core.c` and a few other files, found by pattern match on the v6.14 raw files. `dev-mcelog.c` and `bert.c` are cited by function name only.
8. PL1 = 200 W / PL2 = 250 W / PL4 = 425 W are the values read today. I have not compared them with Intel's defaults for the 285K.
9. The scratch directory is session-specific. Copy `decode_mcelog.py`, `decode_bert.py` and `proposed_additions.sh` somewhere durable if they are to be kept.
