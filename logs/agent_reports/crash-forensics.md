## Verdicts

| Crash | Faulting function / instruction | CPU | Verdict |
|---|---|---|---|
| A. update-manager #GP, 2026-10-05 15:25:13 | `_Py_dict_lookup` (0x572340) at 0x57246a: `movswq (%r9,%r8,2),%rbx` | 0 (from rseq in core) | Transient CPU/register corruption: architecturally impossible state, memory sane |
| B. python3.11 segfault, 15:27:13 | `inversion_rule+85` (pegen.c:360, inlined `_PyPegen_is_memoized`): `mov (%rdx,%rax,8),%rdx` | 0 (kernel line) | Corrupted data: fault address is exactly 1 bit (bit 31) from a plausible heap address; memory vs register undetermined (no core) |
| D. localedef ×2 | unknown (no binary, no Code: bytes in repo) | 0, 0 (as quoted in report) | Undetermined; values are not few-bit flips of a valid pointer |
| D. libcuda 580 #GP | unknown (library no longer installed) | not derivable | Undetermined |
| E1. kernel oops 13:11:42 | `__mem_cgroup_uncharge+0x16`: `mov %rax,-0x8(%rbp)` | 0 | Transient CPU corruption: architecturally impossible fault, no memory in the address dataflow |
| E2. kernel oops 13:19:00 | `_nv012508rm+0x3c` [nvidia]: `cmp %rsi,(%rax)` | 15 | Ordinary software consequence of E1 (dangling pointer into the dead thread's stack) |

Every hardware-suspect event with a known CPU ran on CPU 0 (5 of 5: localedef ×2, B, A, E1). None of my commands died with a signal. Scratch files are in `/tmp/claude-1000/-home-yuming-pytorch-segfault-investigation/e125738b-62b9-4ee7-be34-c517d0a9ccdc/scratchpad/crash-forensics/` (unpacked core in `um/`, disassembly in `um_dis_full.txt`, scripts `oops_an.py`, `ab_an.py`, `decode.py`).

## A. update-manager (python3.12) general protection fault

**Observed**
- Unpacked with `apport-unpack`; gdb on `/usr/bin/python3.12` + `um/CoreDump`. Core `rip=0x57246a rsp=0x7fff61cfa140` matches the kernel line. `si_code=128` (SI_KERNEL), signal 11.
- Native backtrace: `#0 0x57246a` ← `PyDict_GetItemWithError+61` ← `_PyEval_EvalFrameDefault` ← `PyEval_EvalCode` … `Py_RunMain`. The other 4 threads are idle in glib `poll`/`g_cond_wait`. No py-bt (python3.12-dbg not installed).
- Registers: `rax=0x1000 rbx=rdi=r11=0x7519f56ce2c0 (dict) rcx=0x37dcfac0 rdx=r8=r12=0xb0129ed4c81b2a1d rsi=r14=0x7519f56e3430 (key) r9=0x37dceac0 r10=0xb r13=0x37dceaa0 r15=0x7ff eflags=0x10297`.
- Code from function entry to the fault (register-only dataflow for r8):
  ```
  57236f: mov  %r12,%r8          ; r8 = hash
  57237b: movzbl 0x8(%r13),%r10d ; log2_size
  57238b: shl  %cl,%r15 ; 57238e: sub $1,%r15   ; mask
  572392: and  %r15,%r8          ; bytes 4d 21 f8 -> i = hash & mask
  5723ac: lea  0x20(%r13),%r9 ; 5723b7: lea (%r9,%rax,1),%rcx
  5723bb: cmp $7,%r10d ; jg 572460 ; 572460: cmp $0xf,%r10d ; jg
  57246a: movswq (%r9,%r8,2),%rbx   <== #GP
  ```
- Effective address = `r9 + 2*r8 = 0x60253da9c8133efa`, non-canonical, hence #GP error 0.
- Memory is sane:
  - The keys object at 0x37dceaa0 has `dk_log2_size=0x0b`, `dk_log2_index_bytes=0x0c`, `dk_kind=1`, usable 698, nentries 667.
  - The dict has `ma_used=593` and `ma_keys=0x37dceaa0`.
  - The key is the str `"gameconqueror"` with stored hash 0xb0129ed4c81b2a1d; the saved perturb at `-0x38(%rbp)` holds the same hash.
  - The correct slot `indices[hash & 0x7ff = 0x21d]` at 0x37dceefa (inside `[heap] 0x36236000-0x380fb000`) holds -1, so the lookup should have returned "not found".
- Every register matches a first-probe execution except r8:
  - `r15=0x7ff` is the mask; `rax=0x1000` is `1<<12`; `rcx = r9+0x1000`.
  - `rbx` is still the caller's value.
  - The flags equal the result of `cmp $0xf,%r10d` with r10d=0xb.
  - r8 holds the unmasked hash, i.e. its value before the `and`.
- Whole-binary disassembly shows the faulting block is reachable only from 0x5723bf, 0x572457 and 0x57254f, each directly after an `and %r15,%r8` with no intervening write to r8 or r15. The two re-probe paths are excluded by rax, rdx, rsi and the unshifted perturb.
- `actual r8 XOR intended (0x21d) = 0xb0129ed4c81b2800`, Hamming distance 23. This is not a bit flip; it is exactly "mask not applied".
- `dpkg -V python3.12-minimal python3.12 libpython3.12-stdlib` is clean. Apport (itself python3.12, same page-cache text) wrote the crash file within the same second. The core does not contain the text pages (FileSiz 0 for 0x420000).

**Inference**
- No software path and no DRAM fault explains `r8 == r12` with `r15 == 0x7ff`: the dataflow is r12 → r8 → AND with r15, all registers.
- A persistent corrupted text page is excluded, because apport would have died on its first dict lookup.
- Two CPU-side transients remain and cannot be told apart from the core:
  - the AND result was lost or a stale register value was used;
  - a transient single-bit error in the fetched bytes `4d 21 f8`. Three of the 24 single-bit variants reproduce the entire observed state: `4d 20 f8` (`and %r15b,%r8b`), `4d 21 f9` (`and %r15,%r9`), `4d 21 fa` (`and %r15,%r10`).

## B. python3.11 segfault

**Observed**
- The line is now in `journalctl -k -b -6`, not -5 (boot indices shifted). Code: `… 49 8b 56 08 49 63 c7 4c 8d 24 c5 00 00 00 00 <48> 8b 14 c2 48 8b 42 28 …`.
- The 64 Code: bytes equal the on-disk bytes at file offset 0x204e95−42 (compared programmatically).
- The text LOAD has offset = vaddr = 0xf1000, so the load base is 0x642fce1f1000 and the ELF vaddr of the fault is 0x204e95.
- Preceding instructions: `mov 0x10(%r14),%r15d` (p->mark); `cmp 0x14(%r14),%r15d` (fill); `mov 0x8(%r14),%rdx` (p->tokens); `movslq %r15d,%rax`; then the faulting load `p->tokens[p->mark]`.
- Error code 4 is a user-mode read of a not-present page at a canonical address.
- The fault address 0x642f4f3d2f70 is 2030 MiB below the first byte of the binary; nothing can be mapped there (brk heap is above .bss, mmap is at 0x7…).
- End of .bss is 0x642fce7b0338; the brk start window is [0x642fce7b1000, 0x642fd07b1000).
- Exactly one single-bit neighbour of the fault address lands in the heap window: bit 31, giving 0x642fcf3d2f70 (12.1 MiB above .bss).
- If the pointer were intact, `mark` would need to be in int32 0xe7d843ee..0xf0184587, which no single flip of a small non-negative index produces.
- No core exists (`/var/lib/apport/coredump` is empty), so the registers are unknown.

**Inference**
- Consistent with bit 31 cleared in the 64-bit tokens pointer or in the computed address. Whether the bad value was in RAM (the `Parser` struct) or only in a register cannot be determined.
- An ordinary software bug is implausible: the parser is deterministic and the identical command then passed 5 times.
- The instruction bytes in memory were intact at fault time.

## C. CPU attribution

- **update-manager:** the "traps:" line and the core notes carry no CPU, and ProcStatus has no processor field. I derived it from glibc's rseq area in the core: `__rseq_offset=2336`, `__rseq_size=32` (registered). The faulting thread's area at `fs_base+0x920 = 0x7519fa3a09a0` reads `cpu_id_start=0, cpu_id=0`. The same offset in the other threads reads 14, 13, 17 and 5, so the field is live. The kernel refreshes it on every return to user mode after a context switch, so the faulting instruction ran on CPU 0.
- **python3.11:** the kernel line says "likely on CPU 0 (core 0, socket 0)".

## D. Historic lines (addresses only)

- **localedef:** both ips share page offset 0x51c, consistent with the same instruction under ASLR. The report's "same Code: bytes" claim cannot be checked; the raw April journal is not in the repo.
  - 0x18 is a NULL base plus 0x18.
  - 0xfee0fff7 has a zero upper half and is unaligned (minus 0x18 gives 0xfee0ffdf).
  - Neither is a 1–2-bit flip of a valid 47-bit pointer; both are whole-value-wrong, the same class as A.
  - 0xfee0xxxx resembles the LAPIC/MSI address prefix; I treat that as possible coincidence.
- **libcuda:** a user #GP with error 0 means the address was wrong in bits 63:47 or was a non-pointer value (as in A); a low-bit flip would give a segfault instead. `sp:7fff96dffb00` is the main-thread stack. ip − vm_start is 0x2fa7ff and the printed file offset is 0x4607ff.

## E. Kernel oopses of 2026-10-07

### E1 (log line 1241, CPU 0, pid 7668)

**Observed**
- objdump of the Code: bytes from function start: `nopl; push %rbp; mov %rsp,%rbp; sub $0x30,%rsp; mov %gs:0x28,%rax; <mov %rax,-0x8(%rbp)>; xor %eax,%eax; cmpq $7,0x38(%rdi)`. The `<48>` marker is byte 42, which is function +0x16.
- `RBP=ffffb46d4f12f608`, `RSP=ffffb46d4f12f5d8` (= RBP−0x30). EFLAGS 0x10286 matches the result of `sub $0x30,%rsp`. RAX holds the canary 85bd2842d5081100, which also appears in four other frames.
- The store's only operand is RBP−8 = ffffb46d4f12f600, 8 bytes below the slot `push %rbp` had just written:
  - The stack dump starts at f608 with the saved RBP ffffb46d4f12f638, then the return address `__folio_put+0x8d`.
  - The frame chain f608→f638→f658→f668→f698 is self-consistent.
  - The target is therefore in the same 4K page as the two preceding successful writes.
- CR2=000045957ee10d90, error 0x0002 (supervisor write, not present), "PGD 0 P4D 0".
- CR2 is unrelated to visible state:
  - Hamming distance 44 to the expected address;
  - at least 19 to every register and all 174 dumped stack words;
  - no value shares its low 16 bits;
  - no base+index×scale(+gs)+disp32 form over the saved registers reaches it.
- No MCE, Xid, NMI or lockup message precedes it in that boot. The "bad frame pointer" WARNING is the slot at f698, where the frame-pointer-less NVIDIA blob stored a heap pointer in RBP.

**Alternatives excluded**
- Previous instruction (gs canary load): it is a read at ffff8ed7bf800028 and it completed.
- NMI clobbering CR2: `exc_nmi` saves and restores CR2, and it would still need a genuine first fault on a hot stack page.
- CET shadow stack: error bit 6 is clear, and `mov` is not a shadow-stack access.
- KPTI: the header says NOPTI and the thread is on its task stack.
- Lazy vmalloc fault: the same page was just written, and CR2 would be in the kernel half.
- RBP corrupted then restored: registers are saved live by the exception entry and nothing restores RBP.
- Hardware breakpoint: DR7=0x400. DR6=ffff07f0 also appears on CPU 15, so it is the platform baseline.
- SMAP: that would give P=1.
- Misdelivered interrupt: the exception frame is well-formed.
- Corrupted instruction bytes: no encoding reaches that address with these registers.

**Inference**
- The CPU generated or latched a wrong linear address for a store whose address comes purely from registers (RSP → RBP → RBP−8). No DRAM contents are involved, so a DIMM fault cannot explain this event.
- The value looks like a user-half pointer. Chromium/Electron and gjs processes on this machine do map in that range (checked in current `/proc/*/maps`), so it may be a stale value from another context. That is unverifiable.

### E2 (line 1653, CPU 15, nvidia-smi pid 9848)

**Observed**
- Code: `mov 0x10(%rax),%rcx; test; je; mov %rcx,%rax; <cmp %rsi,(%rax)>; ja …` — a binary-tree walk.
- `RAX=RCX=CR2=ffffb46d4f12f8a8`, `RSI=0x2678` (9848, its own TID). Page-table line ends "PTE 0" (unmapped vmalloc page).
- The address is 0x2d0 above E1's RSP, inside pid 7668's stack among the NVIDIA frames. A word 0x1df4 (7668) sits in [f8a8, f8b8] by frame-anchor counting.
- It "exited with irqs disabled" and "preempt_count 1".

**Inference**
- NVIDIA's resource manager keeps a stack-allocated per-thread node, keyed by TID, in a global tree. E1 killed thread 7668 mid-call, so the node was never unlinked, and the next lookup dereferenced the freed stack.
- It then died holding a spinlock with IRQs off, which explains the hang; the journal ends the same second. This is not an independent hardware event.

### Other blocks in that log
- Lines 1609 and 1702 are the kernel's "executive summary" reprint of the first oops's registers; the second carries live control registers from CPU 15. Neither is a new fault.
- Line 1625 is "scheduling while atomic" from `make_task_dead`. Its user frame shows RIP 0x7e21af31b4cd (libc `poll`), ORIG_RAX 0xdb, and "Unable to access opcode bytes".

## Cross-crash reading

- **Supports a core-0 CPU fault over DRAM:** A and E1 are register-only dataflows that produced impossible values, on the same P-core, with memory verified sane.
- **Fits both:** B looks like a classic single-bit error but is equally explained by a register or address-generation error.
- **Low-confidence hypothesis:** in both A and E1 the wrong value involves the destination of a 64-bit reg-reg `mov` issued a few instructions earlier (`mov %r12,%r8`; `mov %rsp,%rbp`). This would fit a rename or physical-register fault on core 0, but it rests on two samples.
- **Not determined:** execution versus instruction-fetch error in A; RAM versus register in B; the instructions for D; the origin of E1's CR2 value. The pstore dumps, BERT record, `/dev/mcelog` and kernel image were not readable without root.
- **Operational note:** after any oops in the NVIDIA close path, the next driver call (including `nvidia-smi`) will oops and can deadlock the machine, so reboot first.
