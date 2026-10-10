## Scope and method
All data read-only via `journalctl`, `/var/log/{syslog,kern.log,auth.log,apport.log.1,unattended-upgrades/}`, `sar -f`, `last -x`, file mtimes (`find -newermt`), `/sys`, and `/home/yuming/.config/Claude/logs/main.log`. Per-boot dumps are in `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/timeline/` (`boot_mN.log`, `kern_mN.log`, N = boot index without the minus sign). None of my commands died with a signal.

Boot index note: the task's question 4 calls the 2026-10-06 11:29 boot "-4"; with 7 boots it is now **-5**. I use letters A–G plus the current index. "Reset #1" = end of boot B, "Reset #2" = end of boot E.

## 0. Findings the caller does not have yet
- **F1 (FACT)** Both MCE resets happened while `unattended-upgrade` (system python3.12 + apt, run by `apt-daily-upgrade.service`) was running. These are the only two runs of it on this install.
  - Run 1: journal `2026-10-06T12:15:45.616141 systemd[1]: Starting apt-daily-upgrade.service`, never finished. Last line in `/var/log/unattended-upgrades/unattended-upgrades.log` is `2026-10-06 12:35:22,226 INFO package libnvidia-gl-550 not upgraded`.
  - Run 2: `/var/lib/systemd/timers/stamp-apt-daily-upgrade.timer` mtime 2026-10-07 12:37:04.518, `/var/lib/apt/daily_lock` 12:37:04.556, the log's mtime 12:37:04.769. The log ends in 559 NUL bytes, exactly the length of its 5-line start header.
  - The only other system-python3.12/apt workload seen, `update-manager` on 10-05, took a general protection fault 63 s after launch.
  - `systemctl list-timers`: next `apt-daily-upgrade.timer` run is **Thu 2026-10-08 06:40:57 CEST**.
- **F2 (FACT)** Reset #1 came 46–93 s after the 1 h all-core OCCT load ended. The screenshot taken at 12:35:26 shows one thread busy at near-top turbo: `P-core 4 Usage 100.00 %`, `Core 4 Clock 5648.03 MHz`, total CPU usage 5.6 %, other cores at 800 MHz.
  - CPUs 0 and 4 are the preferred cores: `acpi_cppc/highest_perf` = 66 versus 64 for CPUs 1–3 and 5–7.
  - MSR 0x1AD in `logs/rootdiag/20261007_133822/msr.tsv` is `3636363636363939`: 57x for 1–2 active cores, 54x for 3–8.
  - INFERENCE: the 100 % thread was `unattended-upgrade`.
- **F3 (FACT)** Boot D (2026-10-06 13:42) also ended uncleanly, during a user-requested power-off. That is a third unclean end before today's hang.
- **F4 (FACT)** pstore was empty at the boots after both MCE resets (`systemd-pstore.service ... skipped because of an unmet condition check (ConditionDirectoryNotEmpty=/sys/fs/pstore)`), although `efi_pstore` was registered in boots B and E. INFERENCE: the kernel never reached its panic path.
- **F5 (FACT)** The root diagnostics collected at 13:38:22 (`/home/yuming/pytorch-segfault-investigation/logs/rootdiag/20261007_133822/`) show for the current boot:
  - `dmidecode.txt`: `Wake-up Type: Power Switch`.
  - `mcelog.bin` is 0 bytes and every MCi_STATUS in `mca_banks.tsv` is zero.
  - `BERT.data.bin` is 44532 bytes: error_severity=1, 14 sections, all CPER type `81212a96-09ed-4996-9471-8d729c8e69ed` (firmware error record) carrying record GUID `8f87f311-c998-4d9e-a0c4-6065518c4f6d`.
  - INFERENCE: this is Intel CrashLog, and being far over the kernel's print limit is why it prints "Skipped 1 error records".
  - INFERENCE: if today's reset was a power cycle, MCA banks would be cleared anyway, so "BERT without mce" in boot G is not a clean negative control. SMBIOS wake-up type may not distinguish a reset button from a power cycle; ask the user.
- **F6 (FACT)** Secure Boot was `enabled` in boots A–D and `disabled` in E–G, so BIOS setup was entered between 10-06 13:43 and 13:50.
- **F7 (FACT)** The journal loses its tail on hard resets. `/var/log/syslog` and file mtimes show the machine alive later than the last journal entry in both cases (section 2).
- **F8 (FACT)** pstore holds two dumps, not three: `001` under `1791371502` (13:11:42, 20 parts) and `002` split across `1791371937` (13:18:57, parts 01–13) and `1791371940` (13:19:00, parts 14–18). The second oops therefore began about 13:18:57, not 13:19:00.

## 1. Per-boot table (CEST)
| Boot | idx / ID | Kernel t0 → last persisted journal entry | End | Final 5 minutes |
|---|---|---|---|---|
| A | -6 `40947ce2` | 10-05 14:56:21.0 → 17:14:10.756 `Journal stopped` | Clean power-off (`17:14:07.513 The system will power off now!`) | OCCT Combined 1 h: sar 98.1 % user, ldavg ~53, 59 GB used through 17:10:00. Screenshots 17:13:23 and 17:13:32. |
| B | -5 `389546b6` | 10-06 11:29:32.07 → 12:35:26.428 | **Abrupt, Reset #1** | OCCT Memory 11:34:58–12:34:58 (last sar sample 12:30:05: 98.5 % user, ldavg-1 26.47, 81 % memory). `unattended-upgrade` running since 12:15:46. User returned 12:35:22 and saved the screenshot at 12:35:29.107. |
| C | -4 `9db536cb` | 10-06 12:36:53.07 → 13:41:59.577 `Journal stopped` | Clean reboot (`13:41:56.414 The system will reboot now!`) | OCCT Memory run 2 from 12:37:42 to 13:37:42 (34 % CPU, ldavg ~8.4, 52.8 GB). Idle from 13:37:42; screenshot 13:38:43; Claude Desktop started 13:40:12. No `unattended-upgrade`. |
| D | -3 `ed0413ae` | 10-06 13:42:29.07 → 13:43:14.318 | **Unclean** | Autologin, power-off requested 13:42:54.195. Last entry `systemd-logind[1345]: Session 1 logged out. Waiting for processes to exit.` No `Journal stopped`, no wtmp shutdown record, last file mtime 13:43:14.816. |
| E | -2 `8a359560` | 10-07 12:32:51.01 → 12:36:31.555 | **Abrupt, Reset #2** | Claude Desktop started 12:34:06; assistant loop-mounted `/media/yuming/Ventoy/memtest86-usb.img` at 12:35:23 and read the MemTest86 log until 12:35:41; idle from 12:35:52. `apt-daily-upgrade` fired 12:37:04.5. No sar sample. |
| F | -1 `2f67eed7` | 10-07 12:38:24.05 → 13:19:00.341 | Oops ×2, hang, forced restart | `torture.py` run #9 13:03:43–13:11:43 (sar 13:00–13:10: 3.6 % user). Oops 13:11:42 on CPU 0; oops in `nvidia-smi` on CPU 15 at about 13:18:57. Last file write 13:19:26.64. |
| G | 0 `36170ef0` | 10-07 13:23:05.08 → running | n/a | No fault lines so far. `sudo scripts/collect_root_diag.sh` ran at 13:38:22. |

- What followed boot D: the MemTest86 log starts 11:50:28 UTC (13:50:28 CEST) and its last line is 2026-10-07 10:31:06 UTC (12:31:06 CEST). The machine therefore sat in MemTest86 overnight and boot E followed about 80 s after that last line.
- After boot F: the 13:20 sysstat sample and Claude's ~60 s `main.log` heartbeat are both missing, so userspace froze between 13:19:26.6 and about 13:20:00.
- Firmware timing from `systemd[1]: Startup finished` (firmware + loader): A 17.285+1.581 s, B 17.432+1.594, C 19.704+1.589, E 24.650+1.469, F 25.515+1.459, G 18.318+1.424. Boot D never logged it.
- Journald logged `system.journal corrupted or uncleanly shut down` at boots C, E, F and G. `last -x` shows `crash` for the sessions of B, D, E and F.

## 2. The abrupt ends

### Reset #1 (boot B → C)
Last persisted journal lines, trimmed:
```
12:25:26.305 apt.systemd.daily[46708]: tar: .remove-on-upgrade /etc/dbus-1/system.d/org.freedesktop.PackageKit.conf: Not found in archive
12:25:26.307 apt.systemd.daily[46708]: tar: Exiting with failure status due to previous errors
12:29:39.831 NetworkManager[1402]: dhcp4 (enp130s0): state changed new lease, address=10.157.163.135
12:29:39.858-12:29:49.884 NetworkManager-dispatcher.service start / deactivate
12:30:01.671 CRON[50205]: (root) CMD ([ -x /etc/init.d/anacron ] && ...)
12:30:05.004-.010 sysstat-collect.service start / finished
12:31:35.257-.261 anacron.service: Normal exit (0 jobs run)
12:34:58.965762 rtkit-daemon[1834]: Successfully made thread 53955 of process 53953 owned by '1000' RT at priority 20.
12:34:58.965770 rtkit-daemon[1834]: Supervising 8 threads of 5 processes of 1 users.
12:35:01.678025 CRON[53988]: (root) CMD (command -v debian-sa1 > /dev/null && debian-sa1 1 1)
12:35:22.783805 kernel: Lockdown: systemd-logind: hibernation is restricted; see man kernel_lockdown.7
12:35:26.391217 dbus-daemon[1320]: [system] Activating via systemd: service name='org.freedesktop.hostname1' ... requested by ':1.81' (uid=1000 pid=2760 comm="/usr/libexec/xdg-desktop-portal-gnome")
12:35:26.406860 systemd[1]: Starting systemd-hostnamed.service - Hostname Service...
12:35:26.427861 dbus-daemon[1320]: [system] Successfully activated service 'org.freedesktop.hostname1'
12:35:26.427938 systemd[1]: Started systemd-hostnamed.service - Hostname Service.      <- last journal entry
```
Only in `/var/log/syslog` (lines 7858–7865):
```
12:35:26.393067 gnome-shell[2111]: Window manager warning: Buggy client sent a _NET_ACTIVE_WINDOW message with a timestamp of 0 for 0x2400004
12:35:26.409740 gvfsd-wsdd[54334]: Failed to spawn the wsdd daemon ...
12:35:26.585728 gvfsd-network[54319]: Couldn't create directory monitor on wsdd:/// ...
12:35:29.131693 tracker-miner-fs-3[54409]: (tracker-extract-3:54409): GLib-GIO-WARNING ... /proc/self/mountinfo   <- last syslog line
```
- The last syslog line is followed by 3226 NUL bytes ending exactly on a 4096-byte block boundary. INFERENCE: at least 3226 bytes of later syslog text were lost, possibly more.
- The last kernel line before the reset is the 12:35:22.78 Lockdown line; the one before that is `12:14:51.03 perf: interrupt took too long (31048 > 31026)`. `kern.log` has no NUL run.
- Later signs of life (file mtimes):
  - 12:35:29.107 the screenshot.
  - 12:35:37.402 `~/.config/Claude/Cache/Cache_Data/1e8c11916ec78ef6_0`.
  - 12:35:44.234 `user-1000@…journal~`.
  - `main.log`: last line 12:34:32, then 309 NUL bytes, which is one ~60 s heartbeat line.
- Time of death is bracketed between 12:35:44.2 and about 12:36:31.8.
  - The upper bound is INFERENCE: boot C kernel t0 12:36:53.07 minus 1.589 s loader minus 19.704 s firmware, ±1 s. It assumes the firmware timer counts from a single reset.
- Gap from last journal entry to next kernel start: 86.6 s. The clean reboot C→D took 29.5 s.
- `unattended-upgrade` logged nothing after 12:35:22.226, although its previous step took 14 s.

Boot C hardware-error lines, complete and exact (kernel-monotonic stamps in brackets where taken):
```
ACPI: BERT 0x000000005C2D2000 000030 (v01 INTEL  EDK2     00000001 INTL 00000001)
ACPI: Reserving BERT table memory at [mem 0x5c2d2000-0x5c2d202f]
EDAC MC: Ver: 3.0.0
[0.454780] microcode: Current revision: 0x00000118
[0.454781] microcode: Updated early from: 0x00000117
[0.454806] mce: [Hardware Error]: Machine check events logged
BERT: [Hardware Error]: Skipped 1 error records
BERT: Total records found: 1
```

### Reset #2 (boot E → F)
Last persisted journal lines, trimmed:
```
12:34:01.457965 pkexec[2939]: yuming: Executing command [USER=root] ... [COMMAND=/usr/lib/update-notifier/package-system-locked]
12:34:06.871285 systemd[1759]: Started app-gnome-com.anthropic.Claude-2953.scope
12:34:10.016 gnome-shell[2098]: Window manager warning: Window 0xa00004 has property _NET_STARTUP_ID ...
12:34:10.572 gnome-keyring-daemon[1777]: asked to register item /org/freedesktop/secrets/collection/login/4, but it's already registered
12:35:01.172420 CRON[3454]: (root) CMD (command -v debian-sa1 > /dev/null && debian-sa1 1 1)
12:35:05.813 NetworkManager[1395]: device (wlp129s0f0): no secrets ... Activation: failed for connection 'ASUS-ROUTER-2.4'
12:35:23.326092 kernel: loop11: detected capacity change from 0 to 2097152
12:35:23.349082 kernel:  loop11: p1 p2 p3
12:35:23.458162 udisksd[1374]: Set up loop device /dev/loop11 (backed by /media/yuming/Ventoy/memtest86-usb.img)
12:35:23.488217 udisksd[1374]: Mounted /dev/loop11p1 at /media/yuming/B695-6C88 on behalf of uid 1000
12:35:29.720526 udisksd[1374]: Mounted /dev/loop11p2 at /media/yuming/B695-8CA5 on behalf of uid 1000
12:36:25.641771 com.anthropic.Claude.desktop[2953]: ...atom_cache.cc:236] Add application/vnd.portal.filetransfer to kAtomsToCache
12:36:25.642074 com.anthropic.Claude.desktop[2953]: ...atom_cache.cc:236] Add application/vnd.portal.files to kAtomsToCache
12:36:31.555234 gnome-shell[2098]: Window manager warning: Buggy client sent a _NET_ACTIVE_WINDOW message with a timestamp of 0 for 0x3200004   <- last journal and last syslog line
```
- Syslog then has exactly 139 NUL bytes, mid-block. That is the exact length of the line `… systemd[1]: Starting apt-daily-upgrade.service - Daily apt upgrade and clean activities...` (139 bytes in the 10-06 instance).
- Later signs of life:
  - 12:37:04.518–.769 the timer stamp, apt lock and `unattended-upgrade` log.
  - 12:37:05.016 `system@…journal~`.
  - 12:37:10.770 `~/.config/Claude/Cache/Cache_Data/f1e15c5bf2d778c9_0`.
  - `main.log`: last line 12:36:22, then 320 NUL bytes, which is one heartbeat.
- Time of death is bracketed between 12:37:10.8 and about 12:37:57 (same INFERENCE: 12:38:24.05 − 1.459 − 25.515 s). That is 6–53 s after `unattended-upgrade` started on an idle machine.
- Gap from last journal entry to next kernel start: 112.5 s.

Boot F lines are the same set as boot C, except the mce line comes first:
```
[0.468966] mce: [Hardware Error]: Machine check events logged
[0.468968] microcode: Current revision: 0x00000118
[0.468969] microcode: Updated early from: 0x00000117
```
The `ACPI: BERT …`, `EDAC MC: Ver: 3.0.0`, `BERT: [Hardware Error]: Skipped 1 error records` and `BERT: Total records found: 1` lines are identical.

### The other boots
- Boot G (after today's forced restart): the same BERT table and BERT lines, and no `mce:` line.
- Boots A, B, D and E have no BERT table and no mce line.
- No `HEST`, `GHES`, `ERST` or `APEI` line exists in any boot. The ACPI table list has no HEST, ERST or EINJ.

### Decoded MCE detail
- **FACT** None exists anywhere: no bank, status, addr, misc, CPU, TSC, PROCESSOR or "Machine Check Exception" line in any of the 7 boots. `journalctl -k -b N | grep -B3 -A12 "Machine check events logged"` shows only neighbours such as `Key type dns_resolver registered`, `IPI shorthand broadcast: enabled` and X.509 certificate loads.
- **FACT** `CONFIG_X86_MCELOG_LEGACY=y`; no `rasdaemon` or `mcelog` is installed.
- **INFERENCE** (from kernel-source knowledge, not verified here) The records went only to `/dev/mcelog` and were lost at the next reboot. The BERT regions of boots C and F are overwritten. The details of both events are unrecoverable from Linux.

## 3. Every kernel fault line, all boots
| Time | Line | Context |
|---|---|---|
| 10-05 15:25:13.109 | `traps: update-manager[13350] general protection fault ip:57246a sp:7fff61cfa140 error:0 in python3.12[17246a,420000+2e3000]` (no CPU printed, no Code line) | `/usr/bin/python3 /usr/bin/update-manager --no-update --no-focus-on-map`, started 15:24:10 by update-notifier. Idle desktop (sar 15:20–15:30: 3.8 % user). Core in `/var/crash/_usr_bin_update-manager.1000.crash` (21 MB, owner yuming, not analysed). |
| 10-05 15:27:13.523 | `python[14503]: segfault at 642f4f3d2f70 ip 0000642fce3f5e95 sp 00007fff178c38f0 error 4 in python3.11[204e95,642fce2e2000+240000] likely on CPU 0 (core 0, socket 0)` | `pixi run python -c "import torch,torchvision…"` |
| 10-05 15:27:13.527 | `Code: 44 8b 67 60 45 85 e4 0f 85 a6 0b 00 00 45 8b 7e 10 45 3b 7e 14 0f 84 ed 07 00 00 49 8b 56 08 49 63 c7 4c 8d 24 c5 00 00 00 00 <48> 8b 14 c2 48 8b 42 28 48 85 c0 74 1f 81 38 55 04 00 00 0f 84 42` | same |
| 10-07 13:11:42.435 | `BUG: unable to handle page fault for address: 000045957ee10d90`, `#PF: supervisor write access in kernel mode`, `error_code(0x0002) - not-present page`, `Oops: Oops: 0002 [#1] PREEMPT SMP NOPTI`, `CPU: 0 UID: 1000 PID: 7668 Comm: cuda00001800007`, `RIP: 0010:__mem_cgroup_uncharge+0x16/0x80` | `torture.py` run #9 teardown; last step in the log is 2059. |
| same | `Code: 0f 1f 40 00 90 90 90 90 90 90 90 90 90 90 90 90 90 90 90 90 0f 1f 44 00 00 55 48 89 e5 48 83 ec 30 65 48 8b 04 25 28 00 00 00 <48> 89 45 f8 31 c0 48 83 7f 38 07 76 3a 48 8d 75 d0 48 c7 45 d0 00` | Followed by `WARNING: kernel stack frame pointer at 0000000031115092 in cuda00001800007:7668 has bad value 00000000123da346`, `note: cuda00001800007[7668] exited with irqs disabled`, `Fixing recursive fault but reboot is needed!`, `BUG: scheduling while atomic: cuda00001800007/7668/0x00000000`. |
| 10-07 13:19:00.332 (pstore 13:18:57) | `BUG: unable to handle page fault for address: ffffb46d4f12f8a8`, `#PF: supervisor read access`, `Oops: Oops: 0000 [#2]`, `CPU: 15 UID: 1000 PID: 9848 Comm: nvidia-smi`, `RIP: 0010:_nv012508rm+0x3c/0x310 [nvidia]` | Workflow agents were running. Claude `main.log` at 13:19:00: `[event-loop-stall] main process blocked for 2814ms`. |
| same | `Code: 48 63 47 08 48 01 c2 48 8b 07 48 85 c0 75 1b e9 2b 02 00 00 66 2e 0f 1f 84 00 00 00 00 00 48 8b 48 10 48 85 c9 74 17 48 89 c8 <48> 39 30 77 ef 0f 83 f9 01 00 00 48 8b 48 18 48 85 c9 75 e9 48 89` | Followed by `note: nvidia-smi[9848] exited with irqs disabled` and `exited with preempt_count 1`. |

- Not found in any boot: NVRM Xid, soft lockup, RCU stall, hung task, thermal throttling, `Marking TSC unstable`, clocksource watchdog, bus-lock or runtime split-lock events.
- Benign and load-correlated: `perf: interrupt took too long` 11 times on 10-05 16:xx, 11 times in boot B (11:37–12:14) and 5 times in boot C, all during OCCT.
- Userspace crashes with no kernel line, from `/var/log/apport.log.1` (10-05 only; the current `apport.log` is empty since 10-07 12:32:55):
  - 15:27:14 `pixi` pid 14466, signal 11. INFERENCE: it re-raised its child's signal.
  - 15:43:35 `python -X faulthandler torture.py` pid 20561, signal 11 (run #8). INFERENCE: no kernel segfault line because faulthandler installs a SIGSEGV handler.
  - 16:03:57 and 16:04:05 `/home/yuming/Downloads/OCCT`, signal 6. The session transcript shows `std::logic_error … basic_string::_M_construct null not valid`. INFERENCE: a launcher software abort.

## 4. OCCT
- **FACT** OCCT ran natively on Linux: process `OCCTGUI`, exe `/tmp/OCCT/Resources/OCCTGUI --temp-path=/tmp/OCCT --launcher-exe-path=/home/yuming/Downloads/OCCT`, uid 1000.
  - Boot A: pid 16326, entries 15:38:32–17:13:34.
  - Boot B: pid 3729, entries 11:30:48–11:34:58, in cgroup `app-com.anthropic.Claude-2915.scope`.
  - Boot C: pid 2862, entries 12:37:12–12:37:42.
- **FACT** The screenshot filenames encode 12-hour local time. Each screenshot coincides with an `xdg-desktop-portal-gnome` → `hostname1` activation (the save dialog) at 12:35:26.39 and 13:38:37.18.
- **INFERENCE** Test end times are marked by the rtkit "made thread … RT" line exactly 1 h after the last OCCTGUI start line: 12:34:58.97 in boot B and 13:37:42.5 in boot C.
- **At 12:35:26 on 10-06**:
  - The test had finished 27 s earlier. The screenshot shows 01:00:00 / 01:00:00, "No errors detected", "Schedule - Completed".
  - Package temperature was 62 °C (maximum 80 °C) and memory use 2858 MB.
  - The user had just returned (Lockdown line 12:35:22.78), pressed OCCT's screenshot button, and saved the file at 12:35:29.107.
  - `unattended-upgrade` was mid-run.
  - The machine stayed alive at least 18 s more and reset no later than about 12:36:32.

## 5. Firmware, thermal and power messages at boot
Identical in all 7 boots (FACT):
- `ACPI BIOS Error (bug): Could not resolve symbol [\_SB.PC00.I2C0], AE_NOT_FOUND (20240827/dswload2-162)`, the same for `I2C1`, each followed by `ACPI Error: AE_NOT_FOUND, During name lookup/catalog`.
- `ACPI BIOS Error (bug): Could not resolve symbol [\_SB.PC00.LPCB.HEC.DPTF.FCHG], AE_NOT_FOUND (20240827/psargs-332)` and `ACPI Error: Aborting method \_SB.IETM.CHRG.PPSS due to previous error`.
- `x86/tme: not enabled by BIOS`.
- `x86/split lock detection: #AC: crashing the kernel on kernel split_locks and warning on user-space split_locks`.
- `tsc: Detected 3700.000 MHz processor` / `tsc: Detected 3686.400 MHz TSC`; `clocksource: Switched to clocksource tsc`.
- `CPU0: Thermal monitoring enabled (TM1)`; `ACPI: thermal: Thermal Zone [TZ00] (28 C)`.
- `intel_pstate: Intel P-state driver initializing`, `Hybrid CPU capacity scaling enabled`, `intel_pstate: HWP enabled`.
- `ACPI FADT declares the system doesn't support PCIe ASPM`.
- `NMI watchdog: Enabled`. No iTCO watchdog driver message.

Other observations:
- No `[Firmware Bug]` lines anywhere.
- Wall clock versus monotonic showed zero steps in boot C over 65 min, so the TSC rate is sane. MemTest86's "3750 MHz, ExtClk 101355 kHz" has no Linux-side support.
- Reporting quirk only: `cpuinfo_max_freq` is 4.1 / 4.0 / 3.3 GHz, while OCCT and turbostat show 5.4–5.7 GHz (P) and about 4.6 GHz (E).

## 6. pstore, kdump, apport
- **pstore**: `/sys/fs/pstore` is root-only and empty now (`pstore_ls.txt` in the root diagnostics). `/var/lib/systemd/pstore/` holds the two oops dumps listed in F8; a user-readable copy is in `logs/rootdiag/20261007_133822/pstore/`. Nothing was captured for Reset #1, Reset #2 or boot D.
- **kdump/kexec**: not configured. No `kdump-tools` or `kexec-tools`, no `crashkernel=` on the command line, `kexec_crash_loaded=0`. `kernel.panic=0`, `panic_on_oops=0`, `softlockup_panic=0`, `hardlockup_panic=0`.
- **apport**: `enabled=1`, `core_pattern=|/usr/share/apport/apport …`. `apport.log.1` has six events, all on 10-05 (section 3). `/var/crash` contains only the update-manager report.

## 7. Assessment
- **INFERENCE, high confidence** Both abrupt ends are consistent with a CPU-detected hardware error followed by a warm platform reset.
  - Supporting FACTS: the mce line appears at exactly the two boots after the two unexplained resets and nowhere else; no shutdown sequence was logged; journald reported an unclean journal; syslog has NUL padding; there is no wtmp shutdown record.
  - Limit: with no decoded record, severity and bank are unknown. All that is established is that at least one MCA bank was valid at boot.
- **INFERENCE** The error was not handled by Linux's panic path. Kernel-source reasoning: a Linux-handled fatal #MC would panic, dump to efi-pstore and reboot after about 30 s. pstore worked for today's oopses and was empty after both resets. An instantaneous reset (processor shutdown or IERR) fits better; a failed pstore write in #MC context cannot be excluded.
- **Alternatives and what separates them**:
  - **Power loss, PSU dropout, or held power button**: these are cold starts that clear the MCA banks, so they do not explain the mce line. Disfavoured.
  - **User pressed a reset button after a freeze**: a warm reset keeps the banks, but it still needs a machine check to have happened first. There are no logind `Power key` events in any boot, and none of the user's typed messages mentions a spontaneous reboot on 10-06 or 10-07 12:36. Only the user can settle this.
  - **Watchdog**: no iTCO driver is loaded, there are no lockup messages, and `kern.log` has no NUL padding, so no kernel message preceded either reset by more than about 5 s. Disfavoured.
  - **User-initiated reboot**: excluded for B and E, because no end-session or logind lines were logged and the shutdown was unclean.
- **INFERENCE, medium confidence** The trigger pattern is a lightly-threaded CPU-bound workload at the top turbo bin on a preferred core.
  - Evidence: F1, F2, the CPU 0 segfault, and the `update-manager` fault after 63 s.
  - Boot C idled 4 minutes after an identical OCCT run with no `unattended-upgrade` and survived.
  - This would explain why all-core stress tests pass.
  - Confound: Linux places single threads on CPUs 0 and 4 by preference, so "always CPU 0" does not by itself single out a core.
- **Undetermined**:
  - The exact instant and cause of boot D's unclean end.
  - Whether a machine check occurred during today's hang.
  - What the lost syslog bytes of Reset #1 contained.

Questions for the user:
1. On 10-06 about 12:36 and 10-07 about 12:37, did the PC restart by itself, and did the screen freeze first?
2. Is there a reset button, and how was today's restart done: reset button or held power button?
3. On 10-06 13:43, was the power-off forced?

Capture for next time: MCE details survive only until the following reboot, so `sudo scripts/collect_root_diag.sh` must be the first action after any spontaneous restart. Adding `mce=print_all` to the kernel command line or installing rasdaemon would log them automatically. The 2026-10-08 06:40:57 `unattended-upgrade` run is both a risk and a natural test.
