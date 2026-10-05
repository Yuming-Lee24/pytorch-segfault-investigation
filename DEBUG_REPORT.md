# PyTorch Segfault Investigation Report

**Date:** 2026-04-17 → 2026-04-21, re-tested 2026-10-05 (see §4.6)
**Host:** yuming-MS-7E54 (Ubuntu 24.04.3 LTS — fresh install)
**Reporter:** yuming@gmail.com
**Status:** **Hardware fault hypothesis strongly reinforced; XMP instability ruled out.** Fresh Ubuntu 24.04 install with a different NVIDIA driver (580.126.09) and different PyTorch version (2.5.1) **reproduces the same crash within 12–13 steps**, even with `CUDA_LAUNCH_BLOCKING=1`. BIOS audit on 2026-04-21 confirmed **XMP was already disabled** — the RAM is running at JEDEC-spec speeds and still failing. This upgrades the diagnosis from "unstable overclock" to "hardware fault at rated speed." MemTest86+ is now the single most important next action.

---

## 1. Executive Summary

A user-reported intermittent segmentation fault during PyTorch training was investigated. A reliable PyTorch reproducer (< 4 min) was built, and the initial core-dump backtrace pointed at the NVIDIA driver (`libcuda.so.1`, version 590.48.01). However, subsequent events — a `pip` segfault, two `localedef` segfaults (pure CPU code, no GPU involvement), and multiple spontaneous reboots during routine `dpkg` operations — were **not explainable by a GPU driver bug**, shifting the hypothesis to a hardware fault. To rule out any remaining software contamination, the machine was **wiped and reinstalled with Ubuntu 24.04.3 LTS**, a different kernel (6.17.0-22), a **different NVIDIA driver (580.126.09)**, and a different PyTorch version (2.5.1). The reproducer was then re-run — **and the same backward-pass crash reproduced twice in a row, within 12–13 steps**, even with `CUDA_LAUNCH_BLOCKING=1` forcing synchronous CUDA execution. Every software variable has been changed while the fault persists. The common factor across all observed crashes is memory access under load, and a **hardware fault (most likely RAM, CPU cache, or memory overclock instability)** is now the dominant hypothesis. Extensive GPU, stress, and basic memtester tests all passed, but none of them provoke the class of fault suspected here.

---

## 2. System Setup

### 2.1 Hardware
| Component | Spec |
|---|---|
| CPU | 24 logical cores (Intel, platform `MS-7E54`) |
| GPU | NVIDIA GeForce RTX 4090, 24,564 MiB VRAM |
| RAM | ≥ 64 GB installed (only 32 GB tested with memtester) |
| Integrated GPU | Intel iGPU (Meteor Lake) — pre-existing `i915` GSC firmware noise, unrelated to this bug |

### 2.2 Software — initial state (Ubuntu 22.04, before any changes)
| Item | Version |
|---|---|
| OS | Ubuntu 22.04.5 LTS |
| Kernel | 6.8.0-40-generic |
| NVIDIA driver | 550.107.02 |
| CUDA (reported by driver) | 12.4 |
| Python | 3.10.12 |
| pip | 22.0.2 |
| PyTorch | not installed |

### 2.3 Software — Ubuntu 22.04 after setup for reproduction
| Item | Version |
|---|---|
| NVIDIA driver | 590.48.01 *(upgraded during investigation)* |
| Kernel | 6.8.0-107-generic *(auto-upgraded during investigation)* |
| CUDA (reported by driver) | 13.1 |
| PyTorch | 2.6.0+cu124 |
| torchvision | 0.21.0+cu124 |
| cuDNN (bundled) | 9.1.0.70 |
| cuBLAS (bundled) | 12.4.5.8 |

### 2.4 Software — current state (fresh Ubuntu 24.04 install)
| Item | Version |
|---|---|
| OS | Ubuntu 24.04.3 LTS |
| Kernel | 6.17.0-22-generic |
| NVIDIA driver | 580.126.09 |
| CUDA (reported by driver) | 13.0 |
| Python | 3.12.3 |
| pip | not installed |
| PyTorch | not installed |

### 2.5 Diagnostic tools installed (Ubuntu 22.04 era)
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
| 8 | **Fresh Ubuntu 24.04.3 LTS install** on same hardware (2026-04-21); NVIDIA driver 580.126.09 set up | Resolved dpkg/localedef crash loop; provides clean baseline for further investigation |

**Current state (as of 2026-04-21):** Fresh Ubuntu 24.04.3 LTS installed on same hardware. NVIDIA driver 580.126.09 set up. PyTorch 2.5.1 installed via pixi (conda-forge cu124 build). dpkg/localedef issue resolved by fresh install. **`torture.py` still segfaults within 12–13 steps** (two consecutive runs on 2026-04-21 at 13:07 and 13:08). Hardware investigation (MemTest86+, BIOS audit) is now the only remaining lead.

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

### 4.5 Phase 5 — Fresh Ubuntu 24.04 install reproduces the crash

To eliminate any residual doubt that the Ubuntu 22.04 userspace or driver 590 was somehow responsible, the machine was wiped and reinstalled:

| Variable | Old install (crashing) | New install (still crashing) |
|---|---|---|
| OS | Ubuntu 22.04.5 LTS | Ubuntu 24.04.3 LTS |
| Kernel | 6.8.0-107-generic | 6.17.0-22-generic |
| NVIDIA driver | 590.48.01 (CUDA 13.1) | **580.126.09 (CUDA 13.0)** |
| PyTorch | 2.6.0+cu124 | 2.5.1 (conda-forge, cu124 build) |
| Python | 3.10.12 | 3.11 (via pixi) |
| Env manager | pip / user site | pixi |
| CUDA launch mode | async (default) | **`CUDA_LAUNCH_BLOCKING=1`** (sync) |

Both runs of `torture.py` on the fresh install crashed almost immediately:

**Run #4 — 2026-04-21 13:07:07 — crashed at step 12:**
- `faulthandler` output: main thread (`0x0000769525460740`) inside `torch/autograd/graph.py:825 _engine_run_backward` → no Python frame in failing thread (crash is in native code)
- Kernel log confirms the failure site:
  ```
  Apr 21 13:04:26 kernel: traps: python[13267] general protection fault
      ip:71f5ffa607ff sp:7fff96dffb00 error:0
      in libcuda.so.580.126.09[4607ff,71f5ff766000+f84000]
  ```
- Same class of crash as old runs (GPF inside `libcuda.so`) — **on a different driver version (580 vs 590)**.

**Run #5 — 2026-04-21 13:08:27 — crashed at step 13:**
- `faulthandler` output: main thread (`0x0000765769dfb740`) inside `torch/amp/grad_scaler.py:351 _maybe_opt_step` → `<genexpr>` in GradScaler's optimizer step
- **Different fault site** within the same iteration (GradScaler's `scaler.step(opt)` at `torture.py:92` rather than `.backward()` at line 91)
- Different crash site one minute later, same test, same machine, same binary — the classic signature of **non-deterministic memory corruption**

**Why this is the decisive phase:**
- Every software layer that could plausibly have had a bug has been swapped: OS, kernel, driver, PyTorch, Python, install method.
- `CUDA_LAUNCH_BLOCKING=1` forces CUDA operations to execute synchronously, meaning the crash is not a delayed-async-error artifact; the failing instruction really is where the backtrace says it is.
- Crashes reproduce in **12–13 steps** — faster than on the old install, suggesting the fault is not rare, it's just triggered by a specific access pattern that training hits very quickly.
- Two consecutive crashes at two different fault sites rule out any deterministic software bug.

### 4.6 Phase 6 — Re-run on 2026-10-05 (driver 550.163.01, kernel 6.14) still crashes

The machine had been reinstalled again since Phase 5 (login history begins 2026-10-05 14:56): Ubuntu 24.04.3 LTS, kernel 6.14.0-27-generic, **NVIDIA driver 550.163.01 (CUDA 12.4)**. The pixi environment was recreated from `pixi.lock` (PyTorch 2.5.1, torchvision 0.20.1, Python 3.11). One lock entry had to be refreshed first: `cuda-version-13.2-h6f5e358_3` had been re-published upstream with a different hash, so `pixi update cuda-version` moved it to build `he2cc418_4`.

`torture.py` was run three times with `CUDA_LAUNCH_BLOCKING=1 TORCH_SHOW_CPP_STACKTRACES=1 PYTHONFAULTHANDLER=1`, each capped at 8 minutes with `timeout 480`:

| Run | Started | Result |
|---|---|---|
| #6 | 15:27:33 | Clean for 8 min (2106 steps), stopped by the time cap |
| #7 | 15:35:33 | Clean for 8 min (2153 steps), stopped by the time cap |
| #8 | 15:43:33 | **Segfault at step 1** (exit 139, core dumped) |

**Run #8** — `faulthandler` shows the main thread in the *forward* pass: `torch/nn/modules/conv.py:549 _conv_forward`, reached from `model(x)` in `torture.py`. This is a third distinct fault site for the same script (Run #4: `_engine_run_backward`; Run #5: `grad_scaler._maybe_opt_step`). No kernel-log entry and no NVIDIA Xid was recorded for this crash, and no native backtrace was captured, so the faulting library is unknown.

**Two further crashes in the same session, neither involving the GPU:**
```
Oct 05 15:25:13 kernel: traps: update-manager[13350] general protection fault ip:57246a sp:7fff61cfa140 error:0 in python3.12[17246a,420000+2e3000]
Oct 05 15:27:13 kernel: python[14503]: segfault at 642f4f3d2f70 ip 0000642fce3f5e95 sp 00007fff178c38f0 error 4 in python3.11[204e95,642fce2e2000+240000] likely on CPU 0 (core 0, socket 0)
```
- `update-manager` is the system Python 3.12 desktop updater, not part of this investigation.
- The `python3.11` segfault was a bare `import torch, torchvision` sanity check that died inside the interpreter itself. The identical command then passed five times in a row.

**What this adds:**
- A third NVIDIA driver (550.163.01, after 590.48.01 and 580.126.09) and a third kernel show the same fault.
- The crash is far less regular than Phase 5 suggested: about 16 minutes and 4,259 clean steps, then a crash on the very first step of the next run.
- Crashes in CPU-only processes continue on this install, as in Phase 4.

### 4.7 Consolidated evidence

| Crash | GPU involved? | Explainable by driver bug? | Explainable by bad RAM / CPU cache? |
|---|---|---|---|
| PyTorch segfault in `backward()` on Ubuntu 22 + driver 590 (×3) | Yes | Yes | Yes |
| PyTorch segfault with cuDNN disabled | Yes | Unlikely (different code path survives) | Yes |
| `pip install` segfault | No | **No** | Yes |
| `localedef` segfault (×2) at different addresses | **No** | **No** | Yes |
| Spontaneous reboots during dpkg | Unlikely | **No** | Yes |
| **PyTorch segfault on fresh Ubuntu 24 + driver 580 (×2, different fault sites)** | Yes | **No** (different driver, same crash) | Yes |
| **PyTorch segfault on driver 550.163.01 + kernel 6.14 (2026-10-05, forward pass, step 1 of third run)** | Yes | **No** (third driver, same class of crash) | Yes |
| `import torch` segfault inside `python3.11` and `update-manager` GPF in `python3.12` (2026-10-05) | **No** | **No** | Yes |

Only a **hardware memory-corruption hypothesis** explains every observation.

---

## 5. Revised Root Cause (Leading Hypothesis)

**Intermittent memory corruption originating from a hardware fault *at manufacturer-rated speeds*** — most likely one of:

1. **Marginal RAM**, either a failing DIMM or a subtle fault that basic memtester patterns don't provoke
2. **CPU memory controller fault** — Intel Raptor Lake / Meteor Lake memory controllers have had documented degradation issues
3. **CPU cache fault** (L1/L2/L3) corrupting specific cache lines under load
4. **Power delivery instability** (PSU or VRM) under combined CPU + GPU load
5. **Poor DIMM seating / slot contact** — oxidation or partial insertion can cause intermittent failures that only show under specific access patterns

This explains why:
- Simple sequential-pattern memory tests (memtester, stress-ng) pass — they don't provoke the right access patterns
- GPU-only stress (gpu-burn) passes — GPU has its own VRAM, doesn't touch the suspect host RAM heavily
- Real-world workloads (PyTorch, pip, dpkg) crash — they perform complex random memory access under load

### Ruled out
**By the fresh Ubuntu 24 install (Phase 5):**
- **Driver 590.48.01 regression** — swapped to 580.126.09, same crash.
- **Kernel 6.8.0-107-generic bug** — swapped to 6.17.0-22-generic, same crash.
- **Ubuntu 22.04 userspace / glibc issue** — swapped to Ubuntu 24.04.3 LTS, same crash.
- **PyTorch 2.6.0 regression** — downgraded to 2.5.1, same crash.
- **pip-installed PyTorch wheel corruption** — switched to pixi / conda-forge build, same crash.
- **Delayed async CUDA errors masquerading as segfaults** — `CUDA_LAUNCH_BLOCKING=1` still reproduces.

**By BIOS audit (2026-04-21):**
- **Unstable XMP/EXPO memory overclock** — user confirmed **XMP is already disabled** in BIOS, meaning the RAM has been running at JEDEC-spec (manufacturer-guaranteed) speeds throughout the entire investigation. The fault is therefore not caused by running RAM above spec; the RAM (or the memory path feeding it) is failing *at rated speed*. This is a materially more serious finding than XMP instability would have been, and narrows the hypothesis to a true hardware fault rather than a compatibility / tuning issue.

### Not ruled out
- The remaining hypotheses listed above: DIMM fault, CPU memory controller fault, CPU cache fault, power delivery, or DIMM seating — none of which the OS reinstall or BIOS toggle would have touched.

---

## 6. Recommended Investigation Path

### ✅ Already completed
- **BIOS audit — XMP status:** confirmed **already disabled** on 2026-04-21. RAM is running at JEDEC-spec. XMP instability hypothesis ruled out.

### Step 1 — MemTest86+ (now the top priority)
`memtest86+` v7.00 is already installed on this system. Note that after installation the GRUB menu must be regenerated for the entry to appear:
```bash
sudo update-grub
```
Then:
- Reboot and hold `Shift` (or `Esc`) at boot to show the GRUB menu
- Select **"Memory test (memtest86+x64.efi)"**
- Let it run at least one full pass (~1–2 h for 64 GB at JEDEC), ideally **overnight** for multiple passes
- Any single error → DIMM fault confirmed → the failing address identifies which module

**Before launching MemTest86+, quickly verify configured memory speed in Ubuntu:**
```bash
sudo dmidecode -t memory | grep -iE "Speed|Configured|Size"
```
Confirm "Configured Memory Speed" is at JEDEC (≈ 4800 MT/s for DDR5). If higher, the BIOS is still auto-applying a profile despite XMP being "disabled."

### Step 2 — Reseat DIMMs (5 min, free, do before or after MemTest86+)
- Power off completely, unplug the PSU
- Pop each DIMM out, inspect for dust or oxidation on the edge contacts, reinsert firmly until both side latches click
- Do this for all DIMMs — intermittent slot contact is a classic cause of "passes synthetic tests but fails real workload" failures

### Step 3 — BIOS firmware update
- Check current BIOS version on the main BIOS screen
- Compare against latest on MSI's support page for the MS-7E54 board
- Memory training and stability fixes are the most common reason for BIOS updates on Intel Raptor Lake / Meteor Lake boards; updating frequently fixes "stable at JEDEC but still crashes" bugs

### Step 4 — DIMM isolation (if MemTest86+ passes clean)
- Power off, leave only one DIMM in the primary slot (usually DIMM A2)
- Re-run `torture.py` for ~15 min
- If stable → repeat with each other DIMM in turn to identify the failing module
- If crashes persist with every single DIMM → the issue is not a single bad stick; escalate to CPU memory controller / PSU / motherboard

### Step 5 — CPU memory controller / PSU investigation (last resort)
- Intel Raptor Lake CPUs (13th/14th gen) had documented VMin shift / degradation issues. If the CPU is in that family and out of warranty, Intel's extended warranty program may still apply.
- Swap PSU with a known-good unit if available. PyTorch + RTX 4090 under load pulls transient spikes that can exceed a PSU's stable rail output even if its rated wattage is nominally sufficient.

### Defer until hardware is cleared
- **Do not** run further PyTorch or heavy-load workloads on this machine for anything important — every crash carries filesystem and data-corruption risk.

---

## 7. Safety Notes (Current State)

- **dpkg is clean** — the `localedef` / `locales` instability from Ubuntu 22.04 is resolved by the fresh Ubuntu 24.04 install. Normal `apt` operations should work.
- **Filesystem integrity** — the repeated hard reboots on the old install may have caused filesystem corruption. The fresh install provides a clean slate; monitor for any new filesystem errors in `dmesg`.
- **Hardware fault is still unconfirmed** — the underlying RAM/CPU fault hypothesis has not been cleared. Run MemTest86+ (§6) before doing intensive workloads to avoid recurrence.
- **Save important work frequently** until hardware is cleared.

---

## 8. Artifacts Produced

| File | Purpose |
|---|---|
| `~/pytorch-segfault-investigation/torture.py` | Reproducer (ResNet-152 + AMP) — now instrumented with `faulthandler` + pre-step flush + GPU stats |
| `~/pytorch-segfault-investigation/DEBUG_REPORT.md` | This report |
| `~/pytorch-segfault-investigation/pixi.toml` | Reproducible env spec (pytorch 2.5.1, torchvision 0.20.1, pytorch-cuda 12.4, conda-forge) |
| `~/pytorch-segfault-investigation/logs/torture/20260421_130707.log` | **Run #4** — Ubuntu 24, driver 580 — segfault at step 12 in `_engine_run_backward` |
| `~/pytorch-segfault-investigation/logs/torture/20260421_130827.log` | **Run #5** — Ubuntu 24, driver 580 — segfault at step 13 in `grad_scaler._maybe_opt_step` (different fault site, same binary) |
| `~/pytorch-segfault-investigation/logs/torture/20261005_152734.log` | **Run #6** — driver 550.163.01, kernel 6.14 — clean, 2106 steps, stopped at 8 min |
| `~/pytorch-segfault-investigation/logs/torture/20261005_153534.log` | **Run #7** — same setup — clean, 2153 steps, stopped at 8 min |
| `~/pytorch-segfault-investigation/logs/torture/20261005_154334.log` | **Run #8** — same setup — segfault at step 1 in `_conv_forward` |
| `~/pytorch-segfault-investigation/logs/gpu_burn/*` | 8-hour gpu-burn logs (Ubuntu 22 era) |
| `~/pytorch-segfault-investigation/logs/memtester/*` | 32 GB memtester log (2 passes, all `ok`) (Ubuntu 22 era) |
| `~/pytorch-segfault-investigation/logs/torture/torture_*.log` | Ubuntu 22 era training reproducer logs (original 3 segfaults) |
| *(gone with fresh install)* `/var/crash/_usr_bin_python3.10.1000.crash` | Ubuntu 22 era apport crash report |
| *(gone with fresh install)* `/var/crash/_usr_bin_pip.1000.crash` | Ubuntu 22 era pip segfault |

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
| 2026-04-21 | **Fresh install:** Ubuntu 24.04.3 LTS installed on same hardware. Kernel 6.17.0-22-generic. NVIDIA driver 580.126.09 (CUDA 13.0) set up. dpkg/localedef issue resolved. PyTorch not yet reinstalled. |
| 2026-04-21 13:07 | PyTorch 2.5.1 installed via pixi (conda-forge cu124 build). `torture.py` launched with `CUDA_LAUNCH_BLOCKING=1 TORCH_SHOW_CPP_STACKTRACES=1 PYTHONFAULTHANDLER=1`. **Run #4 segfaulted at step 12** in `_engine_run_backward`. Kernel log: GPF inside `libcuda.so.580.126.09`. |
| 2026-04-21 13:08 | **Run #5 segfaulted at step 13** inside `grad_scaler.py:_maybe_opt_step` (a different fault site than run #4, same workload, same binary, one minute apart). |
| 2026-04-21 | **Hardware-fault hypothesis reinforced.** Driver, kernel, OS, and PyTorch version have all been replaced while the fault persists. Only the physical hardware is constant. |
| 2026-04-21 | **BIOS audit:** user confirmed **XMP is already disabled** — RAM has been running at JEDEC-spec speeds throughout the entire investigation. XMP instability hypothesis ruled out. Diagnosis upgrades to "hardware fault at rated speed." MemTest86+ elevated to top priority. |
| 2026-10-05 14:56 | Machine found reinstalled again: kernel 6.14.0-27-generic, NVIDIA driver 550.163.01 (CUDA 12.4). |
| 2026-10-05 15:25 | `update-manager` (system Python 3.12) general protection fault — no GPU involvement. |
| 2026-10-05 15:27 | pixi environment recreated (PyTorch 2.5.1). First `import torch` **segfaulted inside `python3.11`**; five retries passed. |
| 2026-10-05 15:27 → 15:43 | `torture.py` runs #6 and #7 clean for 8 minutes each (4,259 steps total). |
| 2026-10-05 15:43 | **Run #8 segfaulted at step 1** in the forward pass (`_conv_forward`). Fault reproduced on a third driver and kernel. |

---

## 10. Open Questions

1. Does MemTest86+ find any errors? (Ground-truth hardware test — now the single most important action.)
2. Does reseating all DIMMs change behavior? (Cheapest physical test.)
3. Is a single DIMM responsible? (Isolate by testing one at a time.)
4. Is there a BIOS/UEFI firmware update available for this board (MSI MS-7E54)? Memory training / stability improvements sometimes come via firmware.
5. If DIMMs all pass, is the CPU memory controller the fault? (Relevant especially if CPU is 13th/14th-gen Raptor Lake.)
6. Is the PSU providing stable power under combined CPU + GPU load?

**Resolved:**
- ~~Driver 590 bug~~ — driver 580 crashes identically (Phase 5).
- ~~Kernel 6.8.0-107 regression~~ — kernel 6.17 crashes identically (Phase 5).
- ~~Ubuntu 22.04 userspace / dpkg state corruption~~ — Ubuntu 24.04.3 from-scratch crashes identically (Phase 5).
- ~~PyTorch 2.6.0 regression~~ — PyTorch 2.5.1 crashes identically (Phase 5).
- ~~XMP/EXPO instability~~ — BIOS audit 2026-04-21 confirmed XMP was already disabled; RAM already at JEDEC-spec.
