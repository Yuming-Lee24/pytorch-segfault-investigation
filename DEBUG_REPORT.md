# PyTorch Segfault Investigation Report

**Date:** 2026-04-17 → 2026-04-21; re-tested 2026-10-05 (§4.6); memory tests 2026-10-05 → 2026-10-06 (§4.7); reproduced and localised 2026-10-07 (§4.8)
**Host:** yuming-MS-7E54 (Ubuntu 24.04.3 LTS)
**Reporter:** yuming@gmail.com
**Status (2026-10-07):** **The fault is in the CPU: its first performance core (Linux CPU 0) executes code incorrectly when it runs at top turbo speed.** It can now be reproduced on demand in a few minutes without the GPU. Whether the core is defective or the 17-month-old firmware is to blame is not yet settled; a BIOS update followed by a 15-minute re-test decides it (§5, §6).

---

## 1. Executive Summary

Random segmentation faults during PyTorch training, crashes in unrelated CPU-only programs and spontaneous resets on this workstation have one source: **CPU 0, the first P-core of the Core Ultra 9 285K, mis-executes instructions.**

- **Reproduction.** `import torch` pinned to CPU 0 failed 27 times in 540 runs. The identical test passed 1,189 of 1,189 times on the other 23 CPUs, including CPU 4, which runs at the same 5.7 GHz (§4.8.2).
- **Nature of the fault.** Four events on CPU 0 are impossible for a working processor, for example a store that faults at an address its operands cannot produce. No memory contents enter those computations, so the RAM is not the cause (§4.8.3).
- **Resets.** Two resets provoked by tests on CPU 0 each left a machine-check record naming CPU 0 (§4.8.4).
- **Why it stayed hidden.** A core reaches 5.7 GHz only when the machine is lightly loaded. Every stress test loads many cores, which limits them to 5.4 GHz, so every stress test passed. `torture.py`, `pip`, `localedef` and system updates are all light, single-threaded loads (§4.8.6).
- **Speed dependence.** Held to 5.4 GHz, CPU 0 passed 220 of 220 runs. This is suggestive rather than proven, because failures come in bursts (§4.8.2).
- **`torture.py`.** Confined to CPUs 1–23 it ran nine times, 6,356 steps in all, without a crash (§4.8.7).
- **Not yet settled.** A marginal or defective core fits the evidence best. The BIOS is eight releases behind, though, and Intel has since fixed CPU errata with matching symptoms, so the firmware must be updated before that conclusion is safe. If CPU 0 still fails afterwards, the CPU should be replaced under warranty (§5, §6).

Sections 4.1–4.7 record how the NVIDIA driver, the OS, PyTorch and the RAM were each suspected and cleared between April and October.

---

## 2. System Setup

### 2.1 Hardware
| Component | Spec |
|---|---|
| CPU | Intel Core Ultra 9 285K (Arrow Lake) — 24 cores: 8 P-cores + 16 E-cores |
| Motherboard | MSI PRO Z890-S WIFI (MS-7E54), BIOS 1.A70 dated 2025-04-27 |
| GPU | NVIDIA GeForce RTX 4090, 24,564 MiB VRAM |
| RAM | 64 GB DDR5 — Kingston `KF560C30-32` modules (rated DDR5-6000 CL30 via XMP), running at JEDEC 4800 MT/s, 40-39-39-77. No ECC. |
| Integrated GPU | Intel iGPU — pre-existing `i915` GSC firmware noise, unrelated to this bug |

CPU, motherboard, BIOS, and RAM details are taken from the MemTest86 log of 2026-10-06 (§4.7).

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

### 2.6 Software and firmware — state during Phase 8 (2026-10-07)
| Item | Version |
|---|---|
| OS / kernel | Ubuntu 24.04.3 LTS, 6.14.0-27-generic |
| NVIDIA driver | 550.163.01 |
| PyTorch / Python | 2.5.1 / 3.11.9 (pixi, conda-forge) |
| BIOS | 1.A70 |
| CPU microcode | 0x118 (BIOS carries 0x117; Ubuntu loads 0x118 at boot) |
| Intel ME firmware | 19.0.5.1948 |
| CPU numbering | P-cores are Linux CPUs 0–7, E-cores are CPUs 8–23 |

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

### 4.7 Phase 7 — Memory and combined stress tests all pass (2026-10-05 → 2026-10-06)

After Run #8, the memory test called for in §6 was carried out, along with three OCCT runs. **Every test passed with zero errors.**

| Test | When (local) | Duration | Result |
|---|---|---|---|
| OCCT 17.1.6 — Combined (CPU + GPU + memory) | 2026-10-05, finished ~17:13 | 1 h | No errors detected |
| OCCT 17.1.6 — Memory | 2026-10-06, finished ~12:35 | 1 h | No errors detected |
| OCCT 17.1.6 — Memory | 2026-10-06, finished ~13:38 | 1 h | No errors detected |
| PassMark MemTest86 V11.7 Free (booted from USB) | 2026-10-06, 13:50 → 18:24 | 4 h 33 min, 4 passes | **PASS, 0 errors** |

**MemTest86 details** (from the log; its timestamps are in UTC, two hours behind local time):
- Tests 0–10 and 13 (Hammer test) ran in each of the 4 passes in parallel mode, using 16 of the 24 CPUs (an earlier version of this report said all). The cumulative error count stayed at 0 throughout.
- The log confirms the RAM configuration: 4800 MT/s at 40-39-39-77, i.e. JEDEC speed. This independently confirms the "XMP disabled" finding from the BIOS audit and answers the `dmidecode` check in §6 Step 1.
- The tool used was PassMark MemTest86, not the open-source MemTest86+ that §6 originally named. Both are full RAM testers, so the result answers the same question.
- No HTML report exists. MemTest86 did not write one to the USB stick, so the log is the only record.

**OCCT details** (from the screenshots):
- Combined run: GPU power peaked at 432 W of the 450 W limit, GPU temperature at 67 °C, CPU package at 91 °C, physical memory load at about 58 GB.
- Memory runs: CPU package peaked at 80 °C and 68 °C.

**What this means:**
- **A plain bad-DIMM fault is now much less likely.** In real workloads the machine crashes within minutes to tens of minutes (§4.6: three crashes in about 20 minutes). Six and a half hours of dedicated memory testing (MemTest86 plus the two OCCT Memory runs) with no error is hard to reconcile with a defective memory cell.
- **It is not excluded.** The fault is intermittent, and MemTest86 runs outside the operating system with the GPU idle, so it does not reproduce the thermal and electrical conditions of a training run.
- **The Combined run counts weakly against a simple power-delivery problem.** It loaded CPU and GPU together for an hour without an error, but 432 W was the GPU's peak; its average was about 100 W.
- **Suspicion shifts toward the CPU and motherboard.** The crashing workloads all execute ordinary application code (Python, `localedef`, the CUDA driver), and none of the stress tests that passed check the results of that kind of code.

**An unverified observation worth testing:** every crash where the kernel log names a CPU names CPU 0 — both `localedef` segfaults in §4.4 ("on CPU 0") and the `python3.11` segfault in §4.6 ("likely on CPU 0 (core 0, socket 0)"). Three samples is too few to conclude anything, but a single faulty core would explain why whole-system stress tests pass while ordinary programs crash at random. §6 Step 1 tests this directly.

### 4.8 Phase 8 — Stable reproduction; the fault follows CPU 0 at top turbo (2026-10-07)

Work for this phase is on branch `repro-root-cause`. Everything below was measured on kernel 6.14.0-27, NVIDIA 550.163.01, BIOS 1.A70, microcode 0x118.

#### 4.8.1 Run #9 of `torture.py`: clean, then a kernel oops on CPU 0

Run #9 (13:03:43, `CUDA_LAUNCH_BLOCKING=1`, 8-minute cap) completed 2,059 steps with no error. When `timeout` ended it, the kernel oopsed while the process was being torn down:

```text
BUG: unable to handle page fault for address: 000045957ee10d90
#PF: supervisor write access in kernel mode / error_code(0x0002) - not-present page
CPU: 0 UID: 1000 PID: 7668 Comm: cuda00001800007
RIP: 0010:__mem_cgroup_uncharge+0x16/0x80
Code: ... 55 48 89 e5 48 83 ec 30 65 48 8b 04 25 28 00 00 00 <48> 89 45 f8 ...
RSP: ffffb46d4f12f5d8  RBP: ffffb46d4f12f608  RAX: 85bd2842d5081100
CR2: 000045957ee10d90
```

- The faulting instruction is `mov %rax,-0x8(%rbp)`: it stores the stack canary just below a frame pointer that was pushed two instructions earlier. With `RBP = ffffb46d4f12f608` it can only write to `ffffb46d4f12f600`, which is in the page the same function had just written to.
- The CPU reported the fault at `000045957ee10d90`, an address unrelated to any register or stack word in the dump. No correct execution of this instruction produces that fault, and no memory contents are involved in computing the address, so a bad DIMM cannot explain it.
- A second oops at 13:18:57 (`nvidia-smi`, CPU 15) dereferenced a pointer into the dead thread's freed stack. It is a software consequence of the first oops, not a second hardware event. It died holding a lock with interrupts off, which hung the machine; it was reset by hand.
- Kernel log: `logs/kernel/boot_20261007_123826_kernel.log` (oops at line 1241). pstore copies: `logs/rootdiag/20261007_133822/pstore/`.

#### 4.8.2 A CPU-only reproducer, one CPU at a time

`scripts/core_probe.py` pins work to a single CPU and records failures per CPU. It never touches the GPU and needs no root. Its `spawn` mode runs `taskset -c N python -c "import torch, torchvision"` repeatedly; this is the same command that segfaulted once on 2026-10-05. Each run takes about 1.4 s.

| CPU under test | Condition | Measured frequency | Failed / runs |
|---|---|---|---|
| **CPU 0** | alone | 5.65–5.69 GHz | **13 / 240** |
| **CPU 0** | idle-priority spinner on CPU 0, so it never idles | 5.62–5.65 GHz | **2 / 50** |
| **CPU 0** | E-cores 8 and 12 kept busy | 5.66–5.68 GHz | **12 / 200** |
| CPU 0 | one other P-core kept busy | 5.62–5.66 GHz | 0 / 20 |
| CPU 0 | speculative store bypass disabled for the process | 5.67–5.69 GHz | 0 / 30 |
| **CPU 0** | two other P-cores kept busy (turbo limit drops to 54x) | 5.38–5.40 GHz | **0 / 220** |
| CPU 4 (the other 57x core) | alone | 5.66–5.68 GHz | 0 / 395 |
| CPUs 1–3, 5–7 | alone | 5.48–5.50 GHz | 0 / 554 |
| E-cores, CPUs 8–23 | alone | 4.60 GHz | 0 / 240 |

- **CPU 0 at about 5.7 GHz: 27 failures in 540 runs (5.0 %),** over three separate boots. Failures are `SIGSEGV`, general protection faults, or a Python exception raised from corrupted state.
- **Every other CPU: 0 failures in 1,189 runs.** CPU 4 has the same 57x turbo limit as CPU 0 and passed 395 of 395.
- **CPU 0 at 5.4 GHz: 0 failures in 220 runs.** This points to the top turbo speed as a condition, but it is not proven:
  - Failures come in bursts. At 5.7 GHz there were stretches of 98 and 81 consecutive clean runs, and most of the 5.4 GHz runs fell inside one such quiet stretch.
  - Only two speeds were compared, and the lower one was reached by loading two neighbouring cores, which changes more than the frequency.
  - A fairer test that interleaves the conditions in small random blocks (`scripts/cpu_conditions.sh`) was started. The machine reset itself after 90 runs, before any condition had failed, so the two small rows in the table say nothing yet.
- Keeping CPU 0 out of idle states, or keeping E-cores busy, does not prevent the failures.
- Self-checking compute (hashing, compression, sorting, numpy, 16 MB copies, each verified against a reference digest):
  - Steady, on CPU 4: 2 × 90 s and 2 × 150 s, clean. On CPU 1: 2 × 90 s, clean.
  - Steady, on CPU 0: the first attempt segfaulted within seconds; the second ended in a spontaneous reset about 45 s in (§4.8.4).
  - Bursty, 2 × 15 s per CPU: clean on all 24. This amounts to only a few seconds of work per CPU, too little to count as a pass for CPU 0.
  - No run ever produced a wrong digest; every detected failure was a crash, an exception or a reset.
- Core 0 was at 60–66 °C in the runs where its temperature was logged. CPU 4 reached 76–78 °C in its steady runs without failing.

Raw results: `logs/core_probe/*.tsv`. The `max_temp_c` column in files written before 15:10 is wrong (it read the Wi-Fi sensor); later files read the core under test.

#### 4.8.3 What the crashes look like inside

Four events on CPU 0 are impossible for a correctly working processor. In each, the value that went wrong was computed from registers alone, so no memory contents are involved:

| Event | Instruction | Why it cannot happen |
|---|---|---|
| Kernel oops, 13:11:42 (§4.8.1) | `mov %rax,-0x8(%rbp)` | Fault reported at an address unrelated to `RBP`. |
| PID 27451, 13:56:36 | `movups %xmm0,0x60(%rax)` in `_PyErr_Fetch` | `rax` is a valid pointer, and the two preceding instructions read `0x60(%rax)` and `0x70(%rax)` successfully. The target is mapped and writable and still holds its old value in the core. The kernel reported a write fault at address `0x415`. |
| `update-manager`, 2026-10-05 15:25 | `and %r15,%r8` in `_Py_dict_lookup` | The core shows `r8` still holding the unmasked hash, as if the `and` had not run. Every other register matches normal execution, and the dictionary in memory is intact. The crash file's thread data shows it ran on CPU 0. |
| Kernel UBSAN report, 14:44:14 | bounds check in `__mod_memcg_lruvec_state` | "index 18 is out of range for type 'u8 [55]'". 18 is in range. The process carried on and exited normally. |

The other crashes are consistent with the same fault but do not prove it on their own. In each, a register received a wrong value from a memory load a few instructions earlier, and a core dump cannot show whether the CPU loaded it wrongly or an earlier faulty store had put it there:

| PID | Where | What the core shows |
|---|---|---|
| 27430, 27521, 27563 | `cmp %rax,0x8(%r12)` in `PyTraceBack_Here` | The traceback pointer is `0x6e6f68747970632e` (the ASCII bytes `.cpython`), `0x1c` and `0x8`. |
| 26833 | `mov 0x18(%rax),%rcx` in `PyTuple_Pack` | The tuple free-list head holds `0x8a9d884d400c87bc`, which is the hash of the string `__dict__`, not a pointer. |

- Most failures are one event repeating. Of the 20 crash lines from `python3.11`, 10 are at the same instruction (`PyTraceBack_Here+728`), and 6 of the non-crash failures are the same `TypeError: __traceback__ must be a traceback or None`. All lie on one path: a `KeyError` raised and caught inside `inspect.getattr_static` during `import torch`.
- That path reads and clears three adjacent pointers with a 16-byte access that straddles a cache-line boundary. This may be the specific operation that core 0 gets wrong, but that has not been tested directly.
- The kernel logged 15 `segfault` lines for these tests today, and all 15 say "likely on CPU 0". The 5 general-protection lines do not print a CPU; the two of them that left cores ran on CPU 0 according to the cores. One further line, `python[26519]` on CPU 22 at 13:51:08, is a null-pointer crash triggered on purpose to check that core dumps were being saved.
- The interpreter binary matches its package checksum, and the code bytes the kernel printed match the file on disk in all 15 lines, so the program being executed was not corrupted.
- `gdb` summaries of the five cores: `logs/forensics/`. Fuller analysis: `logs/agent_reports/crash-forensics.md`.

#### 4.8.4 The spontaneous resets are machine checks on CPU 0

Two resets happened while a test was running on CPU 0: at about 14:09 (steady self-check) and at about 15:19 (the interleaved import test). Each left one machine-check record, captured with `sudo scripts/collect_root_diag.sh` and decoded with `scripts/decode_mcelog.py`. The two records are identical apart from the address:

```text
cpu 0, apicid 0, bank 3
status 0xbe000000e1c40400: uncorrected, processor context corrupt
MCACOD 0x0400 (internal timer error), MSCOD 0xe1c4
addr   0x00005b9d2564a239 (first), 0x000062bd607dea30 (second)
```

- Intel's specification update for this CPU family (document 834774, rev 023) lists erratum **ARL050**: a system hang, or a hang with an internal-timer machine check with exactly `MCACOD=400h` and `MSCOD=E1C4h`, following a core C1 exit. Its status is "Fixed", and it was first published in September 2025, after this board's BIOS was built.
- The code pair matches the erratum, but the erratum's trigger does not match these events. ARL050 follows a C1 idle exit, and in the first event CPU 0 had been continuously busy for about 45 s. Both address fields are user-space addresses, and the first one's page offset matches the instruction after a known crash site in `python3.11`. The simpler reading is that core 0 stopped retiring instructions in the same code that segfaults, so these records do not decide between firmware and silicon (§5).
- Two earlier resets logged `mce: [Hardware Error]: Machine check events logged` at the next boot: 2026-10-06 about 12:36 and 2026-10-07 about 12:37. Both happened while `unattended-upgrade`, a single-threaded Python program, was running on an otherwise idle machine. Their records were not captured, so which CPU raised them is unknown. An OCCT screenshot taken about a minute before the first one shows the single busy thread on CPU 4 at 5.65 GHz.
- The firmware also leaves an Intel CrashLog record in the ACPI BERT table after each unclean reset. `scripts/decode_bert.py` lists its sections; decoding their contents needs Intel's own tool.

#### 4.8.5 Firmware is far behind

| Item | Installed | Current |
|---|---|---|
| BIOS | 1.A70 (7E54v1A7, spring 2025) | 7E54v1AE0 (2026-08-03), eight releases later |
| Microcode | 0x118 (loaded by Ubuntu; the BIOS itself carries 0x117) | 0x122 (Intel, 2026-08-11); Ubuntu 24.04 packages 0x11b |
| Intel ME | 19.0.5.1948 | 19.0.11.2289 on other vendors' boards |

Intel's errata list for this CPU includes four that fit the symptoms and were fixed or published after this BIOS: ARL036 (a core may see incorrect data when other cores enter deep sleep), ARL047 (an indirect branch may execute incorrect instructions), ARL050 (above), and ARL037 (hang on C6 entry or exit, still unfixed). Intel's release notes do not say which microcode revision carries which fix. Sources and the full table: `logs/agent_reports/web-bios-microcode.md`.

#### 4.8.6 Why every earlier test passed

- The 285K runs its P-cores at 57x (5.7 GHz) only when at most two P-cores are busy, and only CPUs 0 and 4 are allowed that ratio. With three or more busy the limit is 54x.
- `gpu-burn`, `stress-ng`, OCCT and MemTest86 all load many cores at once, so none of them ever ran CPU 0 above 54x. MemTest86 measured 54x on the boot CPU and used 16 of the 24 CPUs.
- `torture.py` loads the CPU lightly: system CPU use was 3.6 % during run #9. Its main thread therefore often runs alone on a preferred core at 57x, as do `pip`, `localedef`, `import torch`, `update-manager` and `unattended-upgrade`.
- Linux places single-threaded work on CPUs 0 and 4 first, which is why the fault looked random rather than rare.

#### 4.8.7 `torture.py` kept off CPU 0

`CPUS=1-23 scripts/run_torture_loop.sh` confines the script and its DataLoader workers to CPUs 1–23 with `taskset`.

| Runs | Length | Steps | Result |
|---|---|---|---|
| 8 | 75 s each | 311–313 each | all clean |
| 1 | 15 min | 3,860 | clean |

- Nine starts, 6,356 steps, 25 minutes: no crash, clean teardown every time, and no kernel fault line.
- This is supporting evidence, not proof. Unconfined runs have also gone 4,259 steps without a crash (runs #6 and #7), and `taskset` does not keep the kernel or other programs off CPU 0.
- During these runs the main thread used about one core and each DataLoader worker about 4 %, which confirms the light CPU load described in §4.8.6.

### 4.9 Consolidated evidence

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
| **Kernel oops on CPU 0 with a fault address its instruction cannot produce (2026-10-07)** | No | **No** | **RAM: no.** CPU: yes |
| **Pinned `import torch`: 27 failures in 540 runs on CPU 0, none on any other CPU (2026-10-07)** | **No** | **No** | **RAM: no** (same memory, other CPUs clean). CPU: yes |
| **Two machine-check resets, both recorded on CPU 0 (2026-10-07)** | **No** | **No** | CPU: yes |

Phase 8 narrows the "hardware" column to one component: only **CPU 0 mis-executing** explains every row.

Tests that have passed, for comparison:

| Test | Duration | Result |
|---|---|---|
| `gpu-burn` | 8 h | 0 errors |
| `stress-ng` CPU and VM | 8 h each | completed |
| `memtester` 32 GB | 2 passes | all `ok` |
| OCCT Combined | 1 h | no errors |
| OCCT Memory (×2) | 1 h each | no errors |
| MemTest86 V11.7 | 4 passes, 4 h 33 min | 0 errors |

None of these tests ran any core above 54x, which is why they passed (§4.8.6). The per-CPU test of §4.8.2 does reproduce the fault.

---

## 5. Root Cause

### Established

**P-core 0 of the CPU (Linux CPU 0, APIC ID 0) executes instructions incorrectly.**

1. **It follows the core.** The same pinned test fails on CPU 0 and on no other CPU (§4.8.2).
2. **It is the processor, not the data.** Four events on CPU 0 cannot occur on a working processor, and none involves memory contents (§4.8.3).
3. **The resets come from the same core.** Both captured machine-check records name CPU 0 (§4.8.4).
4. **It is consistent across the whole history.** Every kernel crash line that names a CPU names CPU 0: both `localedef` crashes in April, the `python3.11` crash on 2026-10-05, and all 15 on 2026-10-07. The 2026-10-05 `update-manager` core also shows CPU 0.

### Probable

**The fault appears only when CPU 0 runs above 5.4 GHz.** CPU 0 failed 27 of 540 runs at about 5.7 GHz and 0 of 220 at 5.4 GHz (§4.8.2). Failures come in bursts and the test designed to settle this was cut short, so this is not yet proven.

### Open: why core 0

| Candidate | For | Against |
|---|---|---|
| **A marginal or defective core** | The fault is confined to one of eight identical cores. CPU 4 runs the same 5.7 GHz cleanly. A design erratum or a firmware bug would be expected to affect all P-cores alike. At least one published case of an unstable 285K with clean memory tests was cured by replacing the CPU (`logs/agent_reports/web-arl-instability.md`). | Not yet re-tested on current firmware. |
| **Outdated firmware** (BIOS 1.A70, microcode 0x118, ME 19.0.5) | Seventeen months old. Intel has since fixed errata whose descriptions fit (§4.8.5), and the machine-check code pair is the one listed for ARL050. Per-core voltage and frequency handling is under firmware control. | CPU 4 is clean. ARL050's trigger does not match the captured events (§4.8.4). |
| **Board voltage delivery** (BIOS voltage settings, voltage regulator) | A shortfall would show first on the core that needs the most voltage at the highest speed. In five samples CPU 0 was requesting 1.32–1.36 V at 57x against 1.36–1.38 V for CPU 4; the sample is too small to rely on. | Turbo ratios and power limits are at Intel's values, and all-core runs at far higher current pass. |

The first candidate fits best. The three cannot be separated without changing the firmware, the BIOS settings or the hardware (§6).

### Ruled out

- **RAM.** The impossible events compute their bad values from registers alone. The same memory serves every CPU, and only CPU 0 fails. MemTest86, OCCT Memory and `memtester` are clean.
- **GPU and NVIDIA driver.** The reproducer never opens a GPU device, and three driver versions behave the same.
- **OS, kernel, Python, PyTorch.** Three installs and three kernels behave the same. The failing import is single-threaded with a fixed hash seed, so software has no way to fail 5 % of the time on one CPU only.
- **Storage.** The interpreter matches its package checksum, and the code bytes in every crash line match the file on disk.
- **Overheating.** Core 0 was at 60–66 °C during the runs where its temperature was recorded, and thermal-throttle counters are zero.
- **Memory overclock.** XMP is off; the RAM runs at JEDEC 4800.
- **Something special about the boot CPU.** No device's interrupts are routed specifically to CPU 0, no system-management interrupts were counted, and all 24 CPUs run the same microcode revision.

### Not ruled out

- **Power supply.** Never swapped. It would have to affect one core, and only under light load.

**Correction kept from earlier versions:** the CPU is a Core Ultra 9 285K (Arrow Lake). The Raptor Lake degradation issue and its extended warranty do not apply.

---

## 6. What To Do Next

### Step 1 — Keep work away from the fault (now, reversible)

- **Best: limit the P-core turbo ratio to 54 in the BIOS.** This keeps every program, including the kernel and background updates, below the speed at which CPU 0 fails. It costs about 5 % in single-thread speed. Check that it worked with the Step 3 command; expect no failures and a frequency column near 5400.
- **Without a reboot: prefix a job with `taskset -c 1-23`.** This protects that job only. The kernel and every other program still use CPU 0.
- **`unattended-upgrade` runs next early on Thursday 2026-10-08** (currently scheduled for 06:17). Both unprovoked resets happened while it was running, so expect another unless the ratio limit is in place.

### Step 2 — Update the firmware

1. Photograph the BIOS settings first (OC, CPU and voltage pages). The update resets them, and they are the only record of the current voltage configuration.
2. Flash **7E54v1AE0** (2026-08-03) from MSI's support page for the PRO Z890-S WIFI, using M-FLASH inside the BIOS setup, not from Linux.
3. Load defaults. Confirm XMP and "200S Boost" are off and the CPU is on Intel Default Settings.
4. In Linux, record `journalctl -k | grep microcode` and `cat /sys/class/mei/mei0/fw_ver`.

Flashing carries some risk: this board has no BIOS flashback button, and a reset during the flash could leave it unbootable. The risk is small, because the machine sat in the UEFI MemTest86 environment for about 22 hours without a reset, and all the resets have happened in Linux.

### Step 3 — Re-run the reproducer (about 15 minutes)

```bash
.pixi/envs/default/bin/python scripts/core_probe.py sweep --mode spawn --cpus 0,4 --count 50 --rounds 6 --require-mhz 5600
```

This runs 300 pinned imports on each of CPUs 0 and 4. It can reset the machine if CPU 0 is still faulty.

| Result | Meaning |
|---|---|
| CPU 0 fails again | Firmware was not the cause. Go to Step 4. |
| CPU 0 passes 300 of 300 with `avg_mhz` above 5600 | Repeat after a reboot. Two clean sets mean the firmware fixed it. Run `sudo scripts/collect_root_diag.sh` and compare the voltage CPU 0 requests at 57x with the earlier captures. |
| Rows marked `too_slow` | CPU 0 never reached its top speed, so a pass proves nothing. Close other programs and run it again. |

About 60 imports are enough to be 95 % sure of seeing a failure at the measured 5 % rate, but failures come in bursts, so use the full 300.

### Step 4 — Replace the CPU

If CPU 0 still fails on current firmware at default settings, ask Intel for a warranty replacement. The useful evidence is §4.8 of this report, the two decoded machine-check records and the reproducer command. If another Z890 board can be borrowed, trying the CPU in it first would separate the CPU from the board.

### After any spontaneous reset

Run `sudo scripts/collect_root_diag.sh` before anything else. The machine-check record survives only until the next reboot.

---

## 7. Safety Notes (Current State)

- **Results computed on CPU 0 cannot be trusted.** Most failures are crashes, but some were ordinary Python exceptions raised from corrupted state, and one kernel bounds check misfired without stopping anything. Silent wrong results are possible.
- **The machine can reset without warning** during light, single-threaded work. Save often.
- **After a kernel `BUG:` or `Oops` line, reboot before touching the GPU.** On 2026-10-07 running `nvidia-smi` after an oops hung the machine.
- **Filesystem.** Four unclean restarts occurred on 2026-10-07. The journal recovered each time; no filesystem errors have been logged.
- **Core dumps** of the CPU 0 crashes are in `/var/lib/apport/coredump/` (apport keeps only the newest five). They are not copied into this repository.

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
| `~/pytorch-segfault-investigation/0510-test-result/memtest86/MemTest86-20261006-115028_603727.log` | MemTest86 V11.7 log — 4 passes, 0 errors (timestamps in UTC) |
| `~/pytorch-segfault-investigation/0510-test-result/occt-screenshot/OCCT-26105-0513*.png` | OCCT Combined, 1 h, no errors (two views of the same run) |
| `~/pytorch-segfault-investigation/0510-test-result/occt-screenshot/OCCT-26106-123526.png` | OCCT Memory, 1 h, no errors |
| `~/pytorch-segfault-investigation/0510-test-result/occt-screenshot/OCCT-26106-013836.png` | OCCT Memory, second 1 h run, no errors |
| `scripts/core_probe.py` | **Per-CPU reproducer** and self-check (§4.8.2). CPU only, no root |
| `scripts/cpu_conditions.sh` | Compares conditions on one CPU in small interleaved blocks (alone, one or two other P-cores busy, store bypass disabled) |
| `scripts/run_torture_loop.sh` | Runs `torture.py` repeatedly, optionally confined to a CPU list, and records how each run ended |
| `scripts/collect_root_diag.sh` | Root-only capture: machine-check buffer, BERT record, pstore, MSRs, turbostat. Run it straight after any spontaneous reset |
| `scripts/decode_mcelog.py`, `scripts/decode_bert.py` | Decoders for the two captures above. `decode_mcelog.py` has been run on one real record |
| `logs/core_probe/*.tsv` | Every per-CPU test result of 2026-10-07 |
| `logs/forensics/spawn_crash_*.txt` | `gdb` summaries of five CPU 0 crash cores |
| `logs/kernel/boot_*_kernel.log` | Kernel logs of the three boots of 2026-10-07, including the oops |
| `logs/rootdiag/20261007_133822/`, `…_143159/`, `…_152153/` | Root captures. The second and third each hold a machine-check record (`mcelog.decoded.txt`). `dmidecode.txt` contains board and DIMM serial numbers |
| `logs/agent_reports/*.md` | Supporting analyses with sources: crash forensics, journal timeline, firmware and errata research, MemTest86/OCCT facts |
| `logs/torture/summary_20261007_*.tsv` | Run #9 and the runs confined to CPUs 1–23 |
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
| 2026-10-05 ~17:13 | OCCT Combined test, 1 hour — no errors. |
| 2026-10-06 ~12:35, ~13:38 | Two OCCT Memory tests, 1 hour each — no errors. |
| 2026-10-06 13:50 → 18:24 | **MemTest86 V11.7, 4 passes — PASS, 0 errors.** RAM confirmed at 4800 MT/s. |
| 2026-10-07 | Results reviewed. CPU identified as Core Ultra 9 285K (Arrow Lake), correcting earlier Raptor Lake references. RAM demoted from leading suspect; CPU / motherboard / power delivery remain. |
| 2026-10-07 12:37 | Spontaneous reset while `unattended-upgrade` ran; next boot logs "Machine check events logged" (record not captured). |
| 2026-10-07 13:03 → 13:11 | `torture.py` run #9: 2,059 clean steps, then a **kernel oops on CPU 0** during teardown. A follow-on oops in `nvidia-smi` hung the machine; reset by hand. |
| 2026-10-07 13:30 → 13:57 | Per-CPU tests: bursty self-check clean on all 24 CPUs; **pinned `import torch` fails only on CPU 0** (8 of 95; every other CPU 0 of 585). Five core dumps examined. |
| 2026-10-07 14:05 → 14:09 | Steady self-check: CPUs 4 and 1 clean; CPU 0 segfaults, then the **machine resets itself**. |
| 2026-10-07 14:32 | Machine-check record captured: **CPU 0, bank 3, internal timer error, MSCOD 0xE1C4**. |
| 2026-10-07 14:35 → 14:47 | CPU 0 by condition: fails at 5.7 GHz alone, never-idle, or with E-cores busy (27 of 470 in total); **0 of 200 when held to 5.4 GHz**. |
| 2026-10-07 14:48 → 15:13 | `torture.py` confined to CPUs 1–23: nine starts, 6,356 steps, no crash (§4.8.7). |
| 2026-10-07 15:17 → 15:19 | Interleaved CPU 0 test: 90 clean imports, then **another spontaneous reset**. Second machine-check record: again CPU 0, bank 3, same code. |
| 2026-10-07 15:22 → 15:38 | More exposure on healthy cores: CPU 4 passes 300 imports and 300 s of steady self-check at 5.7 GHz; CPUs 1–3, 5–7 pass 300 imports. |

---

## 10. Open Questions

1. **Does CPU 0 still fail on current firmware?** This decides between a firmware cause and a hardware one (§6 Steps 2–4).
2. **Is the fault really confined to speeds above 5.4 GHz?** `scripts/cpu_conditions.sh` interleaves the conditions fairly; its first run was cut short by a reset after 90 imports with no failure in any condition.
3. **Which CPU raised the two unprovoked machine checks** of 2026-10-06 and 2026-10-07 12:37? Their records were lost. The two that were captured both name CPU 0.
4. **Is one specific operation at fault?** Most crashes are on a code path that makes a 16-byte access across a cache-line boundary (§4.8.3). A dedicated test of that access has not been written.
5. **What are the BIOS voltage settings?** They cannot be read from Linux.

**Resolved:**
- ~~Does the fault follow a specific CPU core?~~ — Yes, CPU 0 (§4.8.2).
- ~~Is the CPU at fault?~~ — Yes, its first P-core (§5). Whether the core itself or its firmware is to blame is open question 1.
- ~~Does reseating or isolating DIMMs matter?~~ — No longer relevant; RAM is cleared (§5).
- ~~Does a memory test find errors?~~ — No. MemTest86 V11.7 ran 4 passes with 0 errors, and OCCT Memory passed twice (§4.7).
- ~~Driver 590 bug~~ — driver 580 crashes identically (Phase 5).
- ~~Kernel 6.8.0-107 regression~~ — kernel 6.17 crashes identically (Phase 5).
- ~~Ubuntu 22.04 userspace / dpkg state corruption~~ — Ubuntu 24.04.3 from-scratch crashes identically (Phase 5).
- ~~PyTorch 2.6.0 regression~~ — PyTorch 2.5.1 crashes identically (Phase 5).
- ~~XMP/EXPO instability~~ — BIOS audit 2026-04-21 confirmed XMP was already disabled; RAM already at JEDEC-spec.
