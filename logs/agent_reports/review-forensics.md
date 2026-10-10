## Verdict per claim
- K1: SURVIVES. All 15 python3.11 fault lines carrying a CPU tag say CPU 0; rseq cpu_id=0 in all five cores, including the untagged GPFs 26833/27430. One CPU-22 line exists (error 1).
- K2: SURVIVES, narrower than worded. Class (i), impossible without a CPU error: three verified one-offs plus one new candidate. The 20 reproduced crashes are class (ii) except 27451. Class (iii): only python[26519].
- K3: SURVIVES for the tested workload only: every reproduced crash is one hot path (KeyError raise/catch under `inspect.getattr_static`, called from `torch/_dynamo/trace_rules.py`).
- K4: not examined.
- K5: SURVIVES; forensics cannot separate (a) from (b).
- K6: SURVIVES for RAM/storage/software: no DRAM in the class-(i) dataflows; `/home/yuming/pytorch-segfault-investigation/.pixi/envs/default/bin/python3.11` sha256 081da0fc…e88c equals conda-meta `sha256_in_prefix`; kernel Code bytes equal disk in 15/15 lines.
- K7: WEAKENED for taskset: it confines only the pinned job; interrupts, kernel threads and other processes still run on CPU 0.

Classification:
- (i) pid 27451; oops `/home/yuming/pytorch-segfault-investigation/logs/kernel/boot_20261007_123826_kernel.log:1241`; update-manager core; candidate UBSAN (error 4).
- (ii) PyTraceBack_Here+728 ×10 (27430, 27521, 27563, 17756, 17778, 17837, 17859, 17941, 17954, 18032); 16784; free-list GPFs 26833, 16737, 17798, 17880; FOR_ITER NULL 26758, 16879; 26745; 18012.
- (iii) 26519.

## Strongest objection
Instruction forensics proves mis-execution only for three unrelated single events. Every other crash is class (ii): a register received a wrong value from a memory load ten instructions earlier, which a core cannot distinguish from memory truly holding it. K2 therefore rests on the K1/K3 statistics. Also, 11 of 20 faults sit in one PyErr_Fetch sequence whose 16-byte SSE access (`_PyRuntime+166424`, page offset 0x9f8–0xa07) always straddles a cache line: a narrow corner.

## Errors or overstatements found
1. "All lines naming a CPU name CPU 0" is false: `/home/yuming/pytorch-segfault-investigation/logs/kernel/boot_20261007_132308_kernel.log:1236`, python[26519], libc `__strlen_avx2+29`, address 0, "likely on CPU 22". Probably a deliberate NULL-string test; undocumented.
2. `/home/yuming/pytorch-segfault-investigation/logs/forensics/spawn_crash_26833.txt` "garbage" 0x8a9d884d400c87bc is hash("__dict__") (PYTHONHASHSEED=0 in the core's environment; same value in core 27521). In 26833 that string's hash slot holds heap pointer 0x72fa2e934030: it was popped as a free tuple. A software cascade from one earlier corruption.
3. PyTraceBack_Here faults are not "impossible given saved registers": r12 came from `mov 0x70(%rax),%r12` at +37.
4. Unreported: journal 14:44:14.748, CPU 0, PID 17951: "UBSAN … memcontrol.c:356:31 index 18 is out of range for type 'u8 [55]'", self-contradictory. The process exited 0, so the harness counted a pass; failure rates undercount.
5. `/home/yuming/pytorch-segfault-investigation/logs/core_probe/20261007_140229_spawn.tsv`: CPU 0 0/300 at 5690 MHz within three seconds, evidently not the torch import; command unrecorded, silently outside the 13/220.

## Evidence I verified myself
- 27451 (gdb, in place): one thread; si_code 1, si_addr 0x415; RIP bytes `0f 11 40 60`; rax=0x5cec5d683998, target 0x5cec5d6839f8–a07 in one page of PT_LOAD 0x5cec5d553000–0x5cec5d684000, flagged RW, fully dumped; memory there still equals xmm1. Error 6 excludes COW/write-protect (7), PKU (PKRU 0x55555554) and shadow stack; bare metal. Residual non-CPU path: SMM or kernel clobbering CR2 during a simultaneous genuine fault; not credible.
- PyTraceBack_Here: no call or spill between +37 and +728; the only prior store to that field is `_PyErr_SetObject+266` after `xor %eax,%eax`; single thread, same call chain in three cores. 0x1c/0x34 are the `push %rcx` slot of `_PyErr_SetKeyError` ([rsp]=0x1c in 27521, 0x34 in 27430/27451). ".cpython": 289 aligned heap copies in 27430, none on the stack or in vector registers; origin not found.
- Oops: `65 48 8b 04 25 28 00 00 00 <48> 89 45 f8`, RSP=RBP−0x30, CR2 000045957ee10d90.
- update-manager (decoded in memory): r8=r12=0xb0129ed4c81b2a1d, r15=0x7ff, `and %r15,%r8` at 0x572392.
- 14:35:24: `_PyObject_MakeTpCall+102`, free-list head non-canonical. 14:35:37: `decq 0(%rbp)` in `_PyErr_ChainExceptions.cold+83`, traceback 0x76bb00000000 on a present read-only page (error 7). 14:36:11: FOR_ITER, top of stack NULL. 14:42–14:47: seven PyTraceBack_Here+728 (0x24×4, 0x10, 0x3c×2), two `PyTuple_Pack+176`, one `AttributeError_dealloc+23`.
- Not checked: UBSAN disassembly (vmlinuz root-only); nvidia oops.

## Tests that would settle what is still open
1. Rootless: rerun the CPU 0 reproducer under `setarch -R`; a software bug must then fail identically or never.
2. Rootless: wrapper calling `prctl(PR_SET_SPECULATION_CTRL, PR_SPEC_STORE_BYPASS, PR_SPEC_DISABLE)` before exec (sysfs: "disabled via prctl"); failures vanishing at 5.7 GHz localises the load/store-forwarding path.
3. Rootless: C self-check of a line-straddling 16-byte load/store plus adjacent 8-byte load, against an aligned copy.
4. Root: disassemble `__mod_memcg_lruvec_state+0x205`.
5. Firmware update, then rerun (K5).
