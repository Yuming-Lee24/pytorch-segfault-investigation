# PyTorch Segfault Investigation Report

**Date:** 2026-04-17 → 2026-04-21
**Host:** yuming-MS-7E54 (Ubuntu 22.04.5 LTS)
**Reporter:** yuming@gmail.com
**Status:** **Root cause revised — suspected hardware fault (RAM or CPU/cache). Earlier driver-regression hypothesis ruled out by new evidence.**

---

## 1. Executive Summary

A user-reported intermittent segmentation fault during PyTorch training was investigated. A reliable PyTorch reproducer (< 4 min) was built, and the initial core-dump backtrace pointed at the NVIDIA driver (`libcuda.so.1`, version 590.48.01). However, subsequent events — a `pip` segfault, two `localedef` segfaults (pure CPU code, no GPU involvement), and multiple spontaneous reboots during routine `dpkg` operations — are **not explainable by a GPU driver bug**. The common factor across all crashes is memory access under load, making a **hardware fault (most likely RAM, CPU cache, or memory overclock instability)** the leading hypothesis. Extensive GPU, stress, and basic memtester tests all passed, but none of them would catch the class of fault suspected here.

---

## 2. System Setup

### 2.1 Hardware
| Component | Spec |
|---|---|
| CPU | 24 logical cores (Intel, platform `MS-7E54`) |
| GPU | NVIDIA GeForce RTX 4090, 24,564 MiB VRAM |
| RAM | ≥ 64 GB installed (only 32 GB tested with memtester) |
| Integrated GPU | Intel iGPU (Meteor Lake) — pre-existing `i915` GSC firmware noise, unrelated to this bug |

### 2.2 Software — initial state (before any changes)
| Item | Version |
|---|---|
| OS | Ubuntu 22.04.5 LTS |
| Kernel | 6.8.0-40-generic |
| NVIDIA driver | 550.107.02 |
| CUDA (reported by driver) | 12.4 |
| Python | 3.10.12 |
| pip | 22.0.2 |
| PyTorch | not installed |

### 2.3 Software — after setup for reproduction
| Item | Version |
|---|---|
| NVIDIA driver | 590.48.01 *(upgraded during investigation)* |
| Kernel | 6.8.0-107-generic *(auto-upgraded during investigation)* |
| CUDA (reported by driver) | 13.1 |
| PyTorch | 2.6.0+cu124 |
| torchvision | 0.21.0+cu124 |
| cuDNN (bundled) | 9.1.0.70 |
| cuBLAS (bundled) | 12.4.5.8 |

### 2.4 Diagnostic tools installed
`gpu-burn`, `nvidia-cuda-toolkit`, `stress-ng`, `memtester`, `tmux`, `terminator`, `gdb`.

---

## 3. Changes Made to the Machine

| Step | Action | Reason |
|---|---|---|
| 1 | Upgraded NVIDIA driver `550.107.02` → `590.48.01` via `apt install nvidia-driver-590` | User-requested upgrade |
| 2 | Rebooted to load new kernel module | Required |
| 3 | Installed diagnostic tools listed in §2.4 | Needed for testing |
| 4 | Cloned + built `gpu-burn` at `~/test/gpu-burn/` | GPU stress |
| 5 | Installed PyTorch + torchvision (user site-packages, CUDA 12.4 wheels) | Reproducer |
| 6 | Wrote `~/test/torture.py` — ResNet-152 + AMP training loop | Reproducer |
| 7 | **Kernel auto-upgraded** from `6.8.0-40-generic` → `6.8.0-107-generic` (observed on 2026-04-21) | Unintended side-effect of apt operations |

**Current state:** driver 590.48.01 still loaded; PyTorch installed; dpkg is in a **partially broken state** (`locales` package stuck half-configured because `localedef` segfaults every time).

---

## 4. Diagnostic Methodology & Results

### 4.1 Phase 1 — Hardware stress testing (all PASSED initially)

**GPU — `gpu-burn` 8 hours:**
```text
100.0%  proc'd: 1326075 (50636 Gflop/s)   errors: 0   temps: 71 C
Tested 1 GPUs:  GPU 0: OK
```
Peak 73 °C, zero compute errors.

**CPU — `stress-ng --cpu 0 --cpu-method all` 8 hours:**
```text
cpu  994,857,604 ops  28800s  34,543 ops/s  82.85% CPU per instance
```

**RAM — `stress-ng --vm 4 --vm-bytes 80%` 8 hours:**
```text
vm  2,928,716,512 ops  28801s  101,686 ops/s  99.97% CPU per instance
```

**RAM — `memtester 32G 2 passes`:** all 18 test patterns × 2 passes = 36/36 `ok`.

**`dmesg` during/after stress:** no NVIDIA XID errors, no memory-controller errors.

**At this point, the machine appeared 100% healthy.**

### 4.2 Phase 2 — PyTorch reproducer

`torture.py` = ResNet-152 + FP16 AMP + batch 128 + 8-worker pinned-memory DataLoader.
Nominal load: ~92% GPU util, 14 GB / 24 GB VRAM, 306 W / 450 W, 56 °C.

**Segfault reproduced 3 times (all with same signature):**

| Run | How long until crash | Stack |
|---|---|---|
| #1 | Early warmup | `backward()` → native thread, no Python frame |
| #2 | Step 1000 (~217 s) | same |
| #3 (with cuDNN disabled via `torch.backends.cudnn.enabled = False`) | Similar timing | same |

**Run #3 is critical:** disabling cuDNN entirely *still* produced the same crash. Rules out cuDNN as the fault site and suggests the issue is broader than any single GPU library path.

### 4.3 Phase 3 — Initial (incorrect) conclusion from core dump

Core dump from Run #2 was unpacked and analyzed with `gdb`. The backtrace terminated inside `libcuda.so.1`:

```
#5-17  libcuda.so.1          ← crash site
#18    cuLaunchKernelEx()
#19-29 libcudnn_engines*.so
#30-34 libtorch_cuda.so
#35-47 libtorch_cpu.so (autograd engine)
```

**Initial interpretation:** NVIDIA driver 590.48.01 regression during `cuLaunchKernelEx`.

**Why this was wrong:** a crash in `libcuda.so` is *consistent* with a driver bug, but it's also consistent with **the driver correctly dereferencing a pointer that was corrupted in main memory before it got to the driver**. The backtrace alone cannot distinguish these two scenarios.

### 4.4 Phase 4 — New evidence that invalidates the driver theory

**Evidence A — `pip` segfault (2026-04-19):**
The very first `pip install torch` attempt crashed with **SIGSEGV** mid-install (pure Python + file I/O, no CUDA, no GPU). Pip succeeded cleanly on retry. At the time this was dismissed as a "transient glitch" — in hindsight, this was the first real warning.

**Evidence B — `localedef` segfault during `dpkg --configure`:**

On 2026-04-21 the user attempted to clean up dpkg state to proceed with a driver downgrade. The dpkg operations triggered locale regeneration, which calls `localedef` (a glibc locale-compilation utility — **pure CPU, no GPU involvement whatsoever**).

Journal evidence from two separate boots:
```
Apr 21 09:44:36 kernel: localedef[7019]: segfault at 0x18      ip 000062d47c61151c  on CPU 0
Apr 21 09:49:32 kernel: localedef[4266]: segfault at 0xfee0fff7 ip 00005c83d622d51c  on CPU 0
```

User-captured screenshot of the live terminal also shows:
```
Setting up locales (2.35-0ubuntu3.11) ...
Generating locales (this might take a while)...
  de_DE.UTF-8.../usr/sbin/locale-gen: line 177:  4266 Segmentation fault  (core dumped) localedef ...
  done
  en_AG.UTF-8...
```

**Why this is decisive:**
- `localedef` does not import, link against, or call into any NVIDIA library
- Both crashes happen at the **same instruction** (same `Code:` bytes in the kernel log) — localedef is doing the same thing each time
- But the **fault addresses differ** (`0x18` vs `0xfee0fff7`) — if this were a deterministic software bug, they'd match
- Different fault addresses with the same executing instruction is the classic signature of **non-deterministic memory corruption** (a pointer getting garbage from a bad memory cell between reads)

**Evidence C — unexpected reboots during dpkg operations:**

`last reboot` shows **three reboots in 20 minutes** on 2026-04-21, each correlated with attempts to run `dpkg --configure`:
```
reboot  system boot  6.8.0-107-generic  Tue Apr 21 09:31
reboot  system boot  6.8.0-107-generic  Tue Apr 21 09:47
reboot  system boot  6.8.0-107-generic  Tue Apr 21 09:50
```

Journal log tails show each boot terminating abruptly right after the `localedef` segfault (no graceful shutdown messages) — consistent with a kernel panic or power cycle, not a planned restart.

### 4.5 Consolidated evidence

| Crash | GPU involved? | Explainable by driver bug? | Explainable by bad RAM / CPU cache? |
|---|---|---|---|
| PyTorch segfault in `backward()` (×3) | Yes | Yes | Yes |
| PyTorch segfault with cuDNN disabled | Yes | Unlikely (different code path survives) | Yes |
| `pip install` segfault | No | **No** | Yes |
| `localedef` segfault (×2) at different addresses | **No** | **No** | Yes |
| Spontaneous reboots during dpkg | Unlikely | **No** | Yes |

Only a **hardware memory-corruption hypothesis** explains every observation.

---

## 5. Revised Root Cause (Leading Hypothesis)

**Intermittent memory corruption originating from a hardware fault** — most likely one of:

1. **Marginal RAM**, either a failing DIMM or a subtle fault that basic memtester patterns don't provoke
2. **Unstable memory overclock** (XMP / EXPO profile) causing intermittent bit errors under certain access patterns
3. **CPU cache fault** (L1/L2/L3) corrupting specific cache lines under load
4. **Power delivery instability** under combined CPU + GPU load

This explains why:
- Simple sequential-pattern memory tests (memtester, stress-ng) pass — they don't provoke the right access patterns
- GPU-only stress (gpu-burn) passes — GPU has its own VRAM, doesn't touch the suspect host RAM heavily
- Real-world workloads (PyTorch, pip, dpkg) crash — they perform complex random memory access under load

### Not ruled out
- **Driver 590.48.01** may still have bugs, but it is not responsible for `localedef` or `pip` crashes.
- **Kernel 6.8.0-107-generic** auto-upgrade may have introduced instability, but kernel bugs rarely cause userspace segfaults at random addresses.

---

## 6. Recommended Investigation Path

### Do this first — rule out hardware definitively

**Step 1 — MemTest86+ from USB (outside the OS):**
- Download ISO from https://memtest.org/ on another machine
- Write to USB stick (`dd` / Rufus / Balena Etcher)
- Boot this machine from USB
- **Run for ≥ 4–8 hours** (ideally overnight)
- Any single error → root cause found → replace / reseat DIMM(s)

**Step 2 — BIOS audit:**
- Enter BIOS (Del or F2 at POST)
- **Disable XMP / EXPO memory profile** (run RAM at JEDEC default — a common cause of exactly these symptoms)
- **Disable CPU overclocks / PBO / MCE**
- Reboot into OS, re-run `torture.py` for 30 min — if it's now stable, XMP was the cause

**Step 3 — DIMM isolation** (if memtest86+ uncertain):
- Power off, reseat all DIMMs
- Run with one DIMM only → test → swap → retest (isolates a bad module)

### Defer until hardware is cleared
- **Do not** attempt the driver downgrade (`nvidia-driver-550`) right now — every dpkg operation risks another reboot while the system is unstable
- **Do not** run further PyTorch stress until you know the memory is trustworthy

### If MemTest86+ comes back clean and BIOS is at defaults
Then and only then is it worth revisiting the driver-regression theory:
- Boot into text-only target (GRUB edit: add `systemd.unit=multi-user.target 3`)
- `sudo dpkg --configure -a` (should succeed now if hardware is stable)
- `sudo apt remove --purge 'nvidia-driver-590*' 'nvidia-dkms-590' 'nvidia-utils-590' 'libnvidia-*-590' 'libnvidia-*-590:i386'`
- `sudo apt install -y nvidia-driver-550`
- Reboot, re-run `torture.py`

---

## 7. Safety Notes (Current State)

- **dpkg is broken** — `locales` is half-configured because `localedef` keeps crashing. Do not run `apt` against packages that depend on locales being configured, or further breakage is likely.
- **Filesystem integrity risk** — repeated hard reboots can corrupt the filesystem. Consider running `sudo touch /forcefsck && sudo reboot` once the machine is stable enough to do so.
- **Save important work frequently** until hardware is cleared.

---

## 8. Artifacts Produced

| File | Purpose |
|---|---|
| `~/test/torture.py` | Reproducer (ResNet-152 + AMP) |
| `~/test/DEBUG_REPORT.md` | This report |
| `~/gpu_burn_*.log` | 8-hour gpu-burn logs |
| `~/stress_cpu_*.log`, `~/stress_ram_*.log` | 8-hour CPU / RAM stress logs |
| `~/memtester_*.log` | 32 GB memtester log (2 passes, all `ok`) |
| `~/torture_*.log` | Training reproducer logs (contain the segfault traces) |
| `/var/crash/_usr_bin_python3.10.1000.crash` | Full apport crash report (2.2 GB core + metadata) |
| `/var/crash/_usr_bin_pip.1000.crash` | Earlier pip segfault |
| `/tmp/py_crash2/CoreDump` | Unpacked core dump used for `gdb` backtrace |

---

## 9. Timeline

| Date (local) | Event |
|---|---|
| 2026-04-17 | Driver 550.107.02 → 590.48.01 upgrade, reboot. CUDA reports 13.1. |
| 2026-04-17 → 18 | 8-hour simultaneous stress (gpu-burn + stress-ng CPU + stress-ng RAM) — all PASSED. |
| 2026-04-19 | memtester 32 GB × 2 passes — all `ok`. |
| 2026-04-19 | `pip install torch` **segfaulted once**, succeeded on retry (dismissed as transient — in hindsight: first hardware warning). |
| 2026-04-19 | `torture.py` written; **2 PyTorch segfaults** reproduced within 4 min each. |
| 2026-04-19 | Core dump extracted; backtrace inside `libcuda.so.1`. **Initial conclusion: driver 590 regression.** |
| 2026-04-20 | Report drafted with driver-regression conclusion. |
| 2026-04-21 | **3rd PyTorch segfault** with `cuDNN disabled` → same signature. |
| 2026-04-21 | Attempted driver downgrade. `dpkg --configure` triggered `localedef` segfault. Machine rebooted. |
| 2026-04-21 | Retried dpkg. **`localedef` segfaulted again** at a different address. Machine rebooted. |
| 2026-04-21 | **Root-cause theory revised** from "driver bug" to "suspected hardware memory corruption." |

---

## 10. Open Questions

1. Does MemTest86+ find any errors? (Ground-truth hardware test.)
2. Is XMP/EXPO enabled in BIOS, and does disabling it stop the crashes?
3. Is a single DIMM responsible? (Isolate by testing one at a time.)
4. If hardware is 100% clean, is the **kernel 6.8.0-107-generic auto-upgrade** introducing instability? (Boot into previous kernel 6.8.0-40 from GRUB → retest.)
5. Does driver 590 still exhibit PyTorch-only crashes once hardware is cleared? (Only worth testing after step 1.)
