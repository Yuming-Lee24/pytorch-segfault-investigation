## Scope and method

- Read all 17 files in `/home/yuming/pytorch-segfault-investigation/logs/torture/` (LOGDIR below). The three long logs were read by head/tail plus a grep of every non-`>>> step` line, a step-continuity check and a non-printable-byte scan.
- Also used: `DEBUG_REPORT.md`, `README.md`, `torture.py` (current and `git show 1633862:torture.py`), `scripts/run_torture_loop.sh`, file mtimes, `journalctl` (readable via group `adm`), and source lines in `.pixi/envs/default/lib/python3.11/site-packages`.
- No scratch files were created. None of my commands died with a signal.
- No reproducer is running now (`pgrep -af "torture|run_torture_loop"` empty at 13:35). `summary_20261007_130342.tsv` and `stdout_20261007_130342_run1.log` are stale leftovers of Run #9, not files being written.

Eras, per the report (the logs confirm only the Python paths and header lines):

| Era | OS / kernel | NVIDIA driver | PyTorch / Python | Launch settings |
|---|---|---|---|---|
| A | Ubuntu 22.04, 6.8.0-40 then -107 | 590.48.01 | 2.6.0+cu124 (pip user site), 3.10 | README: `TORCH_SHOW_CPP_STACKTRACES=1 PYTHONFAULTHANDLER=1 python3 -X faulthandler torture.py 2>&1 \| tee`; no `CUDA_LAUNCH_BLOCKING` |
| B | Ubuntu 24.04.3, 6.17.0-22 | 580.126.09 | 2.5.1 (pixi), 3.11 | `CUDA_LAUNCH_BLOCKING=1 TORCH_SHOW_CPP_STACKTRACES=1 PYTHONFAULTHANDLER=1` |
| C | Ubuntu 24.04.3, 6.14.0-27 | 550.163.01 | 2.5.1 (pixi), 3.11 | Same env vars plus `timeout 480` |

- The log header `Driver: 12.4` is `torch.version.cuda` (`torture.py:70`), not the NVIDIA driver version. No torture log records the driver version.
- The header does differ by era: `VRAM total: 25.2 GB` in Era B, `25.4 GB` in Era C.

Thread legend for the faulthandler dumps:
- **QF**: the 8 multiprocessing QueueFeeder threads (`threading.py wait` ← `multiprocessing/queues.py:231 _feed`). They are idle in every dump.
- **PM**: the pin-memory thread.
- **AE**: a thread with `<no Python frame>`.

## Per-log catalogue (observed facts)

**1. `torture_20260419_012227.log`** (04-19 01:22:27, Era A before torch was installed)
- Outcome: Python exception `ModuleNotFoundError: No module named 'torch'` at `torture.py` line 1. Not a crash; no steps.

**2. `torture_20260419_220449.log`** (04-19 22:04:49, Era A)
- Script variant using `torch.hub.load("pytorch/vision","resnet50",weights=None)` at `torture.py:18`.
- Outcome: Python exception `RuntimeError: operator torchvision::nms does not exist`, warning stamp `[W419 22:04:53.09…]`, about 4 s after start. 100-frame C++ trace, all inside import machinery. No steps.

**3. `torture_20260419_220531.log`** (22:05:31, Era A)
- Light script variant: lines read `mem 0.3GB`, 5–6 s per 100 steps, 18.4 steps/s.
- Outcome: truncated. Last line is `step 1800 loss 6.958 mem 0.3GB elapsed 98s`; no error text.
- Run length is bounded at 120 s or less, because the next log starts at 22:07:31.
- Loss 6.912–7.112, mean 7.001.

**4. `torture_20260419_220731.log`** (22:07:31, Era A)
- Outcome: Python exception at `[W419 22:07:34.73]`, about 3 s after start: `RuntimeError: CUDA error: CUBLAS_STATUS_ALLOC_FAILED when calling cublasCreate(handle)`.
- Raised from `scaler.scale(loss).backward()` at `torture.py:37`. C++ trace: autograd thread → `AddmmBackward0` → `gemm<Half>` → `createCublasHandle`.
- No step lines. Not a segfault.

**5. `torture_20260419_220758.log`** (22:07:58, Era A)
- Full-size configuration (`mem 0.6GB`, 22–23 s per 100 steps).
- Outcome: truncated after `step 200 … elapsed 45s`; no error text. The next log starts 53 s after this one.
- Loss 6.945 and 6.992.

**6. `torture_20260419_220851.log`** (22:08:51, Era A, cuDNN default-on, async CUDA) — SEGFAULT
- Last line `step 1000 loss 6.943 … elapsed 217s`, so the crash is in steps 1001–1100, between 217 s and about 239 s after t0.
- 4.61 steps/s; 100-step intervals 23,22,22,21,22,21,22,21,22,21 s. Loss 6.926–6.976. Memory constant at alloc 0.6 / reserved 13.2 / peak 12.3 GB. This script version prints no GPU stats.
- Current thread `0x000079a280a6b640`: `<no Python frame>`; it is listed after PM and before main.
- Main `0x000079a391bff000`: `autograd/graph.py:823 _engine_run_backward` ← `autograd/__init__.py:347` ← `_tensor.py:626 backward` ← `torture.py:37`.
- PM `0x…991fc640` idle: `selectors.py:416 select` ← `queues.py:113 get` ← `pin_memory.py:35 do_one_step`. 8 QF idle.

**7. `torture_20260419_232342.log`** (23:23:42, Era A, same configuration) — SEGFAULT
- Same shape as #6: last line `step 1000 loss 6.982 … elapsed 217s`; 4.61 steps/s; intervals 23,22,21,22,22,21,22,21,22,21. Loss 6.912–6.982.
- Current thread `0x0000762450f07640` `<no Python frame>`; main `0x00007625648f3000` in `_engine_run_backward` ← `torture.py:37`; PM idle in select; 8 QF idle.

**8. `torture_nocudnn_20260420_150742.log`** (04-20 15:07:42, Era A, "nocudnn" by filename only) — SEGFAULT
- The file starts directly with `Fatal Python error: Segmentation fault`. With no step line, fewer than 100 steps completed.
- Current thread `0x000077e8f8dfa640` `<no Python frame>`, listed first (newest thread state).
- Main `0x000077e9f2a43000` in `graph.py:823 _engine_run_backward` ← `torture.py:39`. PM idle in select; 8 QF idle.

**9. `torture_nocudnn_20260421_093800.log`** (04-21 09:38:00, Era A, "nocudnn" by filename) — SEGFAULT
- Last line `step 1400 loss 6.917 … elapsed 273s`, so the crash is in steps 1401–1500, between 273 s and about 293 s.
- 5.13 steps/s; intervals 20,20,19,19,20,19,19,20,19,19,20,20,20,19. Loss 6.911–6.986. Memory figures identical to the cuDNN-on runs (0.6 / 13.2 / 12.3 GB).
- Current thread `0x0000728768dde640` `<no Python frame>`; main `0x0000728885a58000` in `_engine_run_backward` ← `torture.py:39`.
- PM `0x000072878d5fd640` was active: `pin_memory.py:64 pin_memory` (`data.pin_memory(device)`) ← `:98` ← `:41 do_one_step`. This is the only dump where PM is not idle.
- Report context: `localedef` segfault on CPU 0 at 09:44:36, then unclean reboots at 09:47 and 09:50.

**10. `20260421_130707.log`** — Run #4 (04-21 13:07:07, Era B; header `PyTorch: 2.5.1 | cuDNN: 90100 | cuDNN enabled: True`, `VRAM total: 25.2 GB`) — SEGFAULT
- Last line `>>> step 12` (11 steps completed). No loss or stat line, and no timestamps in the log.
- Hard bound on run length: under 80 s, because the next log was opened at 13:08:27.
- Current thread `0x000076943c3a86c0` `<no Python frame>`, listed first.
- Main `0x0000769525460740`: `graph.py:825 _engine_run_backward` ← `autograd/__init__.py:347` ← `_tensor.py:581` ← `torture.py:91`. PM idle in select; 8 QF idle.

**11. `20260421_130827.log`** — Run #5 (04-21 13:08:27, Era B, same header) — SEGFAULT
- Last line `>>> step 13` (12 completed).
- Current thread is MAIN `0x0000765769dfb740`: `torch/amp/grad_scaler.py:351 <genexpr>` ← `:351 _maybe_opt_step` ← `:457 step` ← `torture.py:92` (`scaler.step(opt)`).
- Source line 351 (verified in the pixi env): `if not sum(v.item() for v in optimizer_state["found_inf_per_device"].values()):`.
- Other threads: `0x0000765680bff6c0` `<no Python frame>` (listed first, not current), 8 QF idle, PM idle in select.

**12. `20261005_152734.log`** — Run #6 (10-05, Era C, header `VRAM total: 25.4 GB`) — CLEAN
- No faulthandler output. Last line `>>> step 2106`, mtime 15:35:32.94. 2106 consecutive step lines, no gaps, no non-ASCII bytes.
- `step 2100 … elapsed 477s`, 4.40 steps/s; intervals 22–23 s.
- Loss 6.888–6.983, mean 6.942.
- GPU: utilisation 86–92 %, temperature 54→63 °C, power 312–327 W (mean 320).

**13. `20261005_153534.log`** — Run #7 (10-05, Era C) — CLEAN
- Last line `>>> step 2153`, mtime 15:43:33.397. No gaps.
- `step 2100 … elapsed 467s`, 4.50 steps/s; intervals 21–23 s.
- Loss 6.907–7.005, mean 6.948.
- GPU: 87–92 %, 62–63 °C (started warm), 317–332 W (mean 324).
- Journal: process `OCCTGUI[16326]` first logs at 15:38:32, during this run, and logs again up to 17:13:34.

**14. `20261005_154334.log`** — Run #8 (10-05, Era C) — SEGFAULT
- Last line `>>> step 1` (0 completed). No loss or stat line.
- Timing: the file name gives second 15:43:34; mtime is 15:43:35.762. The dump was therefore complete at most 1.76 s after the log was opened.
- Current thread is MAIN `0x000074d73b824740`, with this stack (innermost first):
  - `torch/nn/modules/conv.py:549 _conv_forward` (`return F.conv2d(...)`) ← `conv.py:554 forward` ← `module.py:1747/1736`
  - `torchvision/models/resnet.py:150` (`out = self.conv2(out)`, in `Bottleneck.forward`) ← `container.py:250` (Sequential)
  - `resnet.py:276` (`x = self.layer4(x)`) ← `resnet.py:285` ← `torture.py:89`
- Other threads: 8 QF idle, PM idle in select. No `<no Python frame>` thread exists.
- No kernel line: the only kernel lines from `journalctl -k -b -6` between 15:20 and 16:00 are the 15:25:13 `update-manager` GPF and the 15:27:13 `python3.11` segfault.
- No core file: `/var/lib/apport/coredump/` is empty and `/var/crash/` holds only `_usr_bin_update-manager.1000.crash`.

**15. `20261007_130343.log`** — Run #9 (10-07, Era C, via `scripts/run_torture_loop.sh`; line 16 exports the three env vars, CAP 480) — user space CLEAN
- No faulthandler output. Last line `>>> step 2059`, mtime 13:11:41.923. No gaps.
- `step 2000 … elapsed 465s`, 4.30 steps/s; intervals 23–24 s.
- Loss 6.898–6.997, mean 6.950.
- GPU: 88–91 %, 53→62 °C, 303–316 W (mean 313). Last stat line: `gpu 91% 62C 313W`.
- Kernel oops is journal-stamped 13:11:42.435 (`journalctl -b -1 -o short-precise`): CPU 0, PID 7668, Comm `cuda00001800007`. That is at most 0.51 s after the last log line.
- No kernel messages at all between 12:39:33 and the oops (`logs/kernel/boot_20261007_123826_kernel.log` lines 1238–1241), so no Xid or NVRM line during the run.

**16. `stdout_20261007_130342_run1.log`**
- Byte-identical to #15 (md5 `49102ced…`). Stderr of Run #9 was therefore empty.

**17. `summary_20261007_130342.tsv`**
- Header line only (`run start end exit last_step log`), mtime 13:03:42.114. The row for run 1 was never written, so Run #9's exit status is not recorded.

## Cross-run analysis

### 1. Crash step and time distribution

| Segfault | Steps completed | Time |
|---|---|---|
| #8 (10-05) | 0 | ≤1.76 s after log open |
| #4 (04-21) | 11 | not logged; run <80 s |
| #5 (04-21) | 12 | not logged |
| nocudnn 04-20 | 0–99 | under about 23 s (inferred from 19–23 s per 100 steps) |
| 04-19 22:08 | 1000–1099 | 217–239 s |
| 04-19 23:23 | 1000–1099 | 217–239 s |
| nocudnn 04-21 | 1400–1499 | 273–293 s |

- Not crashed (censored): #6 at 2105 steps, #7 at 2152, #9 at 2058 (each about 479 s); 22:07:58 at 200 or more steps.
- No segfault was observed between roughly 23 s and 217 s, or after 293 s, in any run.
- Total full-size exposure is about 10,100 steps (about 37 min) over 11 launches, with 7 segfaults and 1 kernel oops.
- Steps 1–13 are about 1.2 % of that exposure (114–127 step-completions) but hold 3 of 7 segfaults; 4 of 7 are below step 100.

Ubuntu 24 only (eras B and C, 6 launches):
- 3 launches died at steps 1, 12 and 13; 3 ran 2058–2152 steps clean.
- Zero crashes in steps 14–2153, which is 6,276 steps (about 24 min).
- 3 crashes in 62 start-up step-completions.
- Under a constant per-step hazard, the chance that all 3 land in the first 13 steps is about (62/6338)³ ≈ 1e-6 (my calculation).
- Per-launch early-death rate is 3/6; the 95 % Clopper-Pearson interval is about 12–88 %.

Era A is different: 3 of 4 segfaults are in steady state (217–293 s), and two of them fall in the same 100-step window. A memoryless process with mean 1000 steps would do that about 5 % of the time.

DataLoader epoch boundaries (workers re-forked at steps 783 and 1565; 782 batches per epoch) coincide with no crash. Each clean run crossed two boundaries.

### 2. Frames and threads at crash

- **Five of 7** (both 04-19 runs, both nocudnn runs, Run #4): the faulting thread is a native thread with no Python frame, while main is blocked in `_engine_run_backward`.
- **One of 7** (Run #5): main thread in `GradScaler.step`, inside the `v.item()` generator at `grad_scaler.py:351`.
- **One of 7** (Run #8): main thread in the first forward pass, `F.conv2d` of a Bottleneck `conv2` (3×3) inside `layer4`. Layers 1–3 had already executed in that same forward.
- **DataLoader workers:** no crash is visible. Workers are separate processes, and no log contains "DataLoader worker (pid …) is killed by signal".
- **Pin-memory thread:** never the crashing thread. It was active in `Tensor.pin_memory()` in 1 of 7 dumps (nocudnn 04-21) and idle in the other 6.
- **QueueFeeder threads:** always idle.
- **Kernel side (Run #9):** the oops is in the NVIDIA close path releasing pinned user pages (`os_unlock_user_pages` → `unpin_user_page`).

### 3. Crashing versus clean runs

- **Throughput:** no slowdown before any crash. The last intervals before each crash are 21–22 s (04-19 runs) and 19–20 s (nocudnn 04-21). Clean runs: 4.40, 4.50 and 4.30 steps/s; crashing Era A runs: 4.61 and 5.13.
- **GPU stats:** they exist only for #6, #7 and #9, and are all normal (63 °C or less, 332 W or less, 86–92 % utilisation). No crashing run printed a stat line.
- **Start temperature:** Run #8 started with the GPU warm (Run #7's last reading was 63 °C / 321 W about 13 s earlier). Run #7 also started warm (62 °C) and was clean.
- **Run #9 versus Run #7:** about 4 % slower and about 11 W lower. The two move proportionally; this is not an anomaly.
- **Preceding event:** #7 (clean) and #8 (crash at step 1) had identical preconditions: each was launched right after a 480 s run was SIGTERM-killed. A preceding teardown therefore does not discriminate (1 of 2).
- **Net:** no in-log metric separates crashing from clean runs. The only separator is era: all 3 clean runs are Era C, and all 3 steady-state crashes are Era A.

### 4. Loss sanity

- 116 printed loss values across all logs; range 6.888–7.112.
- Full-size runs: 6.888–7.005, per-run means 6.942–6.953, against ln(1000) = 6.908.
- No `nan` or `inf` token anywhere (grep).
- Last loss before each crash: 6.943, 6.982, 6.917.
- Limits: loss is sampled only every 100 steps. Runs #4, #5, #8 and nocudnn 04-20 crashed before any loss line. GradScaler would silently skip a step on inf/NaN gradients, which the log cannot show.

## Compact table

| Report # | File (LOGDIR/) | Start (CEST) | Era | Outcome | Last step printed | Elapsed at end | Steps/s | Faulting thread / frame |
|---|---|---|---|---|---|---|---|---|
| – | `torture_20260419_012227.log` | 04-19 01:22:27 | A | ModuleNotFoundError | – | – | – | – |
| – | `torture_20260419_220449.log` | 04-19 22:04:49 | A | RuntimeError (`torchvision::nms`) | – | ~4 s | – | – |
| – | `torture_20260419_220531.log` | 04-19 22:05:31 | A, light | truncated | 1800 | 98 s | 18.4 | – |
| – | `torture_20260419_220731.log` | 04-19 22:07:31 | A | `CUBLAS_STATUS_ALLOC_FAILED` | <100 | ~3 s | – | Python exception in backward |
| – | `torture_20260419_220758.log` | 04-19 22:07:58 | A | truncated | 200 | 45 s | 4.44 | – |
| ? | `torture_20260419_220851.log` | 04-19 22:08:51 | A, cuDNN on | SEGFAULT | 1000 | 217–239 s | 4.61 | AE; main in `run_backward` |
| ? | `torture_20260419_232342.log` | 04-19 23:23:42 | A, cuDNN on | SEGFAULT | 1000 | 217–239 s | 4.61 | AE; main in `run_backward` |
| ? | `torture_nocudnn_20260420_150742.log` | 04-20 15:07:42 | A, "nocudnn" | SEGFAULT | none (<100) | <~23 s | – | AE; main in `run_backward` |
| ? | `torture_nocudnn_20260421_093800.log` | 04-21 09:38:00 | A, "nocudnn" | SEGFAULT | 1400 | 273–293 s | 5.13 | AE; main in `run_backward`; PM active |
| #4 | `20260421_130707.log` | 04-21 13:07:07 | B | SEGFAULT | `>>> 12` | <80 s | – | AE; main in `run_backward` (`torture.py:91`) |
| #5 | `20260421_130827.log` | 04-21 13:08:27 | B | SEGFAULT | `>>> 13` | not logged | – | MAIN, `grad_scaler.py:351` `.item()` |
| #6 | `20261005_152734.log` | 10-05 15:27:34 | C | clean, timeout | `>>> 2106` | 478 s | 4.40 | – |
| #7 | `20261005_153534.log` | 10-05 15:35:34 | C | clean, timeout | `>>> 2153` | 479 s | 4.50 | – |
| #8 | `20261005_154334.log` | 10-05 15:43:34 | C | SEGFAULT | `>>> 1` | ≤1.76 s after log open | – | MAIN, `conv.py:549`, layer4 Bottleneck.conv2 |
| #9 | `20261007_130343.log` (and identical `stdout_…run1.log`) | 10-07 13:03:43 | C | clean, then kernel oops at kill | `>>> 2059` | 478.5 s | 4.30 | kernel: `nvidia_close` → `unpin_user_page` → `__mem_cgroup_uncharge`, CPU 0 |

A "?" means the report's Run #1–#3 cannot be mapped unambiguously to these four logs.

## Patterns

- **FACT** — 7 user-space segfaults are logged, plus 1 kernel oops, in about 10,100 full-size steps (about 37 min) over 11 launches.
- **FACT** — Ubuntu 24 (eras B and C): all 3 segfaults are at step 13 or earlier, and the oops is within 0.5 s of process kill. There is no failure in 6,276 steady-state steps (about 24 min).
- **INFERENCE** — On Ubuntu 24 the hazard is concentrated at process start and exit, not in sustained load. A start/stop loop of very short runs would be a far more efficient reproducer than 8-minute runs, and a quicker A/B for excluding CPU 0.
- **INFERENCE** — This fits the CPU-only victims (`localedef`, `pip`, `import torch`, `update-manager` are all short-lived or starting processes) and the fact that steady-state stress tests pass. Start-up and teardown are heavy in mmap, page faults, pin/unpin and idle-to-load transitions; which of these matters is not determinable from these logs.
- **FACT** — Era A looks different: 3 of 4 segfaults are in steady state at 217–293 s, two in the identical step 1001–1100 window, and all four have the same thread signature.
- **INFERENCE** — The Era A crashes may not share a mechanism with the Ubuntu 24 ones. The report's "same crash across all software stacks" is not supported at the level of signature.
- **FACT** — Crash site by thread: 5 in a no-Python-frame native thread during `backward()`, 2 in the main thread (`.item()` in GradScaler; first forward `conv2d` in layer4). None in a pin-memory or QueueFeeder thread; no DataLoader worker death is logged.
- **INFERENCE** — The no-frame thread is the autograd engine's device thread. Main is blocked in `run_backward`; the thread is absent from Run #8's dump (which never reached backward) and present but idle in Run #5's; and the report's gdb backtrace for an Era A core shows autograd-engine frames.
- **INFERENCE** — Run #4 and Run #5 probably died about 3–6 s after t0, estimated from 11–12 steps at 4.3–4.6 steps/s plus first-step overhead.
- **INFERENCE** — Run #8 died about 2.4 s after its launch, taking launch as the moment Run #7 was killed (15:43:33.4).
- **FACT** — Loss is sane everywhere (6.888–7.112, no NaN/inf); memory counters are constant; there is no throughput, temperature or power precursor.
- **FACT** — Run #8 produced no kernel line and no core file.
- **INFERENCE** — The missing kernel line is expected, not anomalous: faulthandler installs a SIGSEGV handler and re-raises with `raise()`, and the kernel logs only unhandled faults. Future faulthandler runs will also leave no kernel line or CPU number unless a core dump is captured.
- **INFERENCE** — The oops came about 0.3 s after timeout expiry, taking expiry as summary-file mtime + 480 s ≈ 13:11:42.11.
- **INFERENCE** — The missing summary row is consistent with the wrapper hanging after the oops.
- **INFERENCE** — The `CUBLAS_STATUS_ALLOC_FAILED` run (22:07:31) is probably VRAM exhaustion from an oversized configuration while the script was being tuned (memory went from 0.3 GB to 0.6 GB between adjacent logs). It cannot be confirmed.
- **INFERENCE** — The two truncated logs (22:05:31, 22:07:58) were probably stopped with Ctrl-C: in a `| tee` pipeline the KeyboardInterrupt traceback is lost. The cause is not recorded.

## Discrepancies with DEBUG_REPORT.md

- **Four Era A segfault logs, not three (FACT).** §4.2 lists #1 "early warmup", #2 "step 1000 (~217 s)" and #3 "cuDNN disabled, similar timing". The logs show two step-1000 crashes with cuDNN on (04-19), one crash before step 100 labelled nocudnn (04-20 15:07:42, absent from the report timeline), and one step-1400 crash labelled nocudnn (04-21 09:38).
- **The kernel line attached to Run #4 predates it (FACT).** §4.5 quotes `Apr 21 13:04:26 kernel: traps: python[13267] general protection fault ip:71f5ffa607ff sp:7fff96dffb00 … libcuda.so.580.126.09[4607ff,71f5ff766000+f84000]`. Run #4's log was created at 13:07:07, which is 2 min 41 s later.
- **That line is very likely a separate, unlogged crash (INFERENCE).** Three things point the same way:
  - the timestamp mismatch above;
  - a faulthandler-handled SIGSEGV does not produce a kernel line (see Run #8);
  - libcuda is mapped at `0x71f5ff766000`, while Run #4's threads sit at `0x7694…/0x7695…`, a different address-space layout.
  
  The stack pointer `0x7fff96dffb00` suggests the main thread, unlike Run #4's faulting worker thread. The April journal no longer exists, so this cannot be verified.
- **"nocudnn" is not verifiable (FACT), and probably was not in effect (INFERENCE, medium confidence).**
  - Fact: `torture.py:39` in those logs also matches the committed script, where the line `# torch.backends.cudnn.enabled = False` is commented out.
  - Fact: memory figures are identical to the cuDNN-on runs, and throughput is 11 % higher.
  - Inference: PyTorch's non-cuDNN convolution path should be much slower, so cuDNN was probably still on.
  - Consequence: §4.2's "Run #3 is critical" conclusion rests on the filename only.

## Could not be determined

- Which CPU the faulting user-space thread ran on, for any torture segfault.
- The native faulting library or instruction for any run in this directory (no core files remain).
- Exact crash wall-clock times for the April runs: their mtimes were reset to 2026-10-05 15:22 by the git checkout.
- Which of layer4's three blocks Run #8 was in.
- Whether OCCT was actively polling sensors at 15:43:35, when Run #8 crashed.
- Whether Run #9's process received SIGTERM before the oops, and its exit code.
