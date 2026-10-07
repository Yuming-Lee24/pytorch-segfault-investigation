#!/usr/bin/env python3
"""Decode raw 'struct mce' records captured from /dev/mcelog (Linux v6.14 layout).

Usage:
    decode_mcelog.py FILE                 decode a binary capture (cat /dev/mcelog > FILE)
    decode_mcelog.py --text FILE          decode "mce=print_all" style kernel log lines
    decode_mcelog.py --status HEX [--bank N] [--mcgcap HEX] [--misc HEX] [--addr HEX]
                                          decode one IA32_MCi_STATUS value
    decode_mcelog.py --selftest           run the built-in MCACOD / layout checks

Only the python3 standard library is used.

Record layout (arch/x86/include/uapi/asm/mce.h, v6.14, 128 bytes, little endian):

  off size field        off size field         off size field
    0   8  status        56   1  cpuvendor       72   4  socketid
    8   8  misc          57   1  inject_flags    76   4  apicid
   16   8  addr          58   1  severity        80   8  mcgcap
   24   8  mcgstatus     59   1  pad             88   8  synd   (AMD SMCA only)
   32   8  ip            60   4  cpuid (1.EAX)   96   8  ipid   (AMD SMCA only)
   40   8  tsc           64   1  cs             104   8  ppin
   48   8  time          65   1  bank           112   4  microcode
                         66   1  cpu (legacy)   116   4  (padding)
                         67   1  finished       120   8  kflags (zeroed by dev-mcelog.c)
                         68   4  extcpu

read() on /dev/mcelog returns N * 128 bytes (N = number of buffered records, at
most max(32, num_online_cpus())) and needs a user buffer of at least
len * 128 bytes (4096 on a 24-CPU machine); the read empties the buffer.
"""

import argparse
import ctypes
import datetime
import re
import struct
import sys

MCE_FMT = "<7Q4BI4B3I4QI4xQ"
MCE_SIZE = struct.calcsize(MCE_FMT)  # 128
MCE_FIELDS = (
    "status", "misc", "addr", "mcgstatus", "ip", "tsc", "time",
    "cpuvendor", "inject_flags", "severity", "pad",
    "cpuid",
    "cs", "bank", "cpu", "finished",
    "extcpu", "socketid", "apicid",
    "mcgcap", "synd", "ipid", "ppin",
    "microcode",
    "kflags",
)

# ioctl numbers, _IOR('M', n, int) on x86-64 (need CAP_SYS_ADMIN):
MCE_GET_RECORD_LEN = 0x80044D01
MCE_GET_LOG_LEN = 0x80044D02
MCE_GETCLEAR_FLAGS = 0x80044D03   # returns and CLEARS the overflow flag (bit 0)

X86_VENDORS = {0: "Intel", 1: "Cyrix", 2: "AMD", 3: "UMC", 5: "Centaur",
               7: "Transmeta", 8: "NSC", 9: "Hygon", 10: "Zhaoxin", 11: "Vortex"}

# arch/x86/kernel/cpu/mce/internal.h, enum severity_level (v6.14)
SEVERITIES = {0: "NO", 1: "DEFERRED/UCNA", 2: "KEEP", 3: "SOME", 4: "AO",
              5: "UC", 6: "AR", 7: "PANIC"}

# arch/x86/include/asm/mce.h kflags bits (always 0 in /dev/mcelog output)
KFLAGS = ((0, "HANDLED_CEC"), (1, "HANDLED_UC"), (2, "HANDLED_EXTLOG"),
          (3, "HANDLED_NFIT"), (4, "HANDLED_EDAC"), (5, "HANDLED_MCELOG"),
          (6, "IN_KERNEL_RECOV"), (7, "IN_KERNEL_COPYIN"))

INTEL_MODELS = {
    0x97: "Alder Lake-S", 0x9A: "Alder Lake-P", 0xBE: "Alder Lake-N",
    0xB7: "Raptor Lake-S", 0xBA: "Raptor Lake-P", 0xBF: "Raptor Lake-S (refresh)",
    0xAA: "Meteor Lake-H/U", 0xAC: "Meteor Lake-S",
    0xC5: "Arrow Lake-H", 0xC6: "Arrow Lake-S", 0xB5: "Arrow Lake-U",
    0xBD: "Lunar Lake-M", 0xCC: "Panther Lake",
}

# Best publicly available bank -> unit hints for Intel client cores.  Intel does
# not publish a bank table for Lion Cove / Skymont; banks 0-3 follow the
# long-standing Core convention (they are also the only per-core banks that the
# Intel CrashLog "MCA" record for Arrow Lake captures), bank 4 is by convention
# the PCU.  Everything else is unknown.  Treat as a hint, not as fact.
BANK_HINTS = {
    0: "IFU: instruction fetch / front end / L1I+ITLB (Core convention; core scope)",
    1: "DCU: L1 data cache unit (Core convention; core scope)",
    2: "DTLB: data TLB (Core convention; P-core only - E-cores of this machine have no bank 2)",
    3: "MLC: mid-level cache / L2 (Core convention; core scope, L2 is shared by 4 E-cores)",
    4: "PCU: power control unit (convention; package scope) - internal timer/IERR-type codes",
}


def bit(v, n):
    return (v >> n) & 1


def bits(v, hi, lo):
    return (v >> lo) & ((1 << (hi - lo + 1)) - 1)


# --------------------------------------------------------------------------
# MCACOD (IA32_MCi_STATUS[15:0]) - SDM Vol. 3B "Interpreting the MCA Error Codes"
# --------------------------------------------------------------------------
TT = {0: "I (instruction)", 1: "D (data)", 2: "G (generic)", 3: "reserved"}
LL = {0: "L0", 1: "L1", 2: "L2", 3: "LG (generic)"}
RRRR = {0: "ERR (generic error)", 1: "RD (generic read)", 2: "WR (generic write)",
        3: "DRD (data read)", 4: "DWR (data write)", 5: "IRD (instruction fetch)",
        6: "PREFETCH", 7: "EVICT", 8: "SNOOP"}
PP = {0: "SRC (local processor originated request)",
      1: "RES (local processor responded to request)",
      2: "OBS (local processor observed error as third party)",
      3: "generic"}
II = {0: "M (memory access)", 1: "reserved", 2: "IO", 3: "other transaction"}
MMM = {0: "GEN (generic undefined request)", 1: "RD (memory read error)",
       2: "WR (memory write error)", 3: "AC (address/command error)",
       4: "MS (memory scrubbing error)"}

SIMPLE_CODES = {
    0x0000: "No error",
    0x0001: "Unclassified",
    0x0002: "Microcode ROM parity error",
    0x0003: "External error (BINIT# from another processor)",
    0x0004: "FRC (functional redundancy check) error",
    0x0005: "Internal parity error",
    0x0006: "SMM handler code access violation",
    0x0400: "Internal timer error",
    0x0E0B: "I/O error",
}


def decode_mcacod(code):
    """Return (class, human text) for a 16-bit MCACOD value."""
    code &= 0xFFFF
    if code in SIMPLE_CODES:
        return "simple", SIMPLE_CODES[code]
    if code & 0xFC00 == 0x0400:
        return "simple", "Internal unclassified error (sub-code 0x%03x)" % (code & 0x3FF)
    f = bit(code, 12)
    c = code & 0xEFFF        # compound codes are matched with the F bit removed
    ftxt = "; F=1 (correction report filtering: corrected-error reports filtered)" if f else ""
    if c & 0xFFFC == 0x000C:
        return "compound", "Generic cache hierarchy error, level %s%s" % (LL[c & 3], ftxt)
    if c & 0xFFF0 == 0x0010:
        return "compound", "TLB error: %s, level %s%s" % (
            TT[bits(c, 3, 2)], LL[c & 3], ftxt)
    if c & 0xFF80 == 0x0080:
        ch = c & 0xF
        return "compound", "Memory controller error: %s, channel %s%s" % (
            MMM.get(bits(c, 6, 4), "reserved(%d)" % bits(c, 6, 4)),
            "not specified" if ch == 0xF else ch, ftxt)
    if c & 0xFF00 == 0x0100:
        r = bits(c, 7, 4)
        return "compound", "Cache hierarchy error: %s, %s cache, level %s%s" % (
            RRRR.get(r, "reserved(0x%x)" % r), TT[bits(c, 3, 2)], LL[c & 3], ftxt)
    if c & 0xFF80 == 0x0280:
        ch = c & 0xF
        return "compound", "Extended memory error: %s, channel %s%s" % (
            MMM.get(bits(c, 6, 4), "reserved(%d)" % bits(c, 6, 4)),
            "not specified" if ch == 0xF else ch, ftxt)
    if c & 0xF800 == 0x0800:
        r = bits(c, 7, 4)
        return "compound", ("Bus/interconnect error: participation %s, %s, request %s, "
                            "%s, level %s%s") % (
            PP[bits(c, 10, 9)], "TIMEOUT" if bit(c, 8) else "no timeout",
            RRRR.get(r, "reserved(0x%x)" % r), II[bits(c, 3, 2)], LL[c & 3], ftxt)
    return "unknown", "Unrecognised MCACOD 0x%04x (reserved / model specific)" % code


def decode_status(status, mcgcap=None):
    """Return a list of text lines describing IA32_MCi_STATUS."""
    out = []
    names = (("VAL", 63), ("OVER", 62), ("UC", 61), ("EN", 60), ("MISCV", 59),
             ("ADDRV", 58), ("PCC", 57), ("S", 56), ("AR", 55))
    out.append("flags      : " + " ".join("%s=%d" % (n, bit(status, b)) for n, b in names))
    ser = None if mcgcap is None else bool(bit(mcgcap, 24))
    uc, pcc, s, ar, en = (bit(status, 61), bit(status, 57), bit(status, 56),
                          bit(status, 55), bit(status, 60))
    if not bit(status, 63):
        cls = "status not valid (VAL=0)"
    elif not uc:
        cls = "CE  - corrected error"
    elif pcc:
        cls = "UC  - uncorrected, processor context corrupt (fatal; a reset is the only way out)"
    elif ser is False:
        cls = "UC  - uncorrected (CPU has no software error recovery, S/AR undefined)"
    elif s and ar:
        cls = "SRAR - uncorrected recoverable, software recovery action required"
    elif s and not ar:
        cls = "SRAO - uncorrected recoverable, software recovery action optional"
    elif not s and not ar:
        cls = "UCNA - uncorrected, no action required (not signalled via #MC)"
    else:
        cls = "UC  - reserved S/AR combination (S=0, AR=1)"
    if ser is None and uc and not pcc:
        cls += "  [assumes MCG_CAP.SER_P=1; mcgcap unknown]"
    out.append("class      : " + cls)
    if bit(status, 63) and not en:
        out.append("             EN=0: error reporting for this error was not enabled in MCi_CTL")
    if bit(status, 62):
        out.append("             OVER=1: an earlier error in this bank was overwritten/lost")
    out.append("other info : corrected_error_count[52:38]=%d  threshold_status[54:53]=%d  "
               "fw_updated[37]=%d  other[36:32]=0x%x" % (
                   bits(status, 52, 38), bits(status, 54, 53), bit(status, 37),
                   bits(status, 36, 32)))
    mscod = bits(status, 31, 16)
    mcacod = bits(status, 15, 0)
    kind, text = decode_mcacod(mcacod)
    out.append("MSCOD      : 0x%04x (model specific error code, bits 31:16)" % mscod)
    out.append("MCACOD     : 0x%04x  %s" % (mcacod, text))
    return out


def decode_misc(misc):
    mode = bits(misc, 8, 6)
    modes = {0: "segment offset", 1: "linear address", 2: "physical address",
             3: "memory address", 7: "generic"}
    return "addr_lsb[5:0]=%d  addr_mode[8:6]=%d (%s)  [valid only if MCG_CAP.SER_P and MISCV]" % (
        misc & 0x3F, mode, modes.get(mode, "reserved"))


def decode_mcgstatus(v):
    return "RIPV=%d EIPV=%d MCIP=%d LMCES=%d" % (bit(v, 0), bit(v, 1), bit(v, 2), bit(v, 3))


def decode_mcgcap(v):
    return ("banks=%d CTL_P=%d EXT_P=%d CMCI_P=%d TES_P=%d EXT_CNT=%d SER_P=%d "
            "EMC_P=%d ELOG_P=%d LMCE_P=%d" % (
                v & 0xFF, bit(v, 8), bit(v, 9), bit(v, 10), bit(v, 11), bits(v, 23, 16),
                bit(v, 24), bit(v, 25), bit(v, 26), bit(v, 27)))


def decode_cpuid(eax, vendor=0):
    stepping = eax & 0xF
    model = (eax >> 4) & 0xF
    family = (eax >> 8) & 0xF
    if family in (6, 15):
        model |= ((eax >> 16) & 0xF) << 4
    if family == 15:
        family += (eax >> 20) & 0xFF
    name = ""
    if vendor == 0 and family == 6 and model in INTEL_MODELS:
        name = " (%s)" % INTEL_MODELS[model]
    return "family 0x%x model 0x%x stepping %d%s" % (family, model, stepping, name)


def parse_cpulist(text):
    cpus = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            cpus.update(range(int(a), int(b) + 1))
        else:
            cpus.add(int(part))
    return cpus


def fmt_time(t):
    if not t:
        return "0 (not recorded)"
    try:
        utc = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        loc = datetime.datetime.fromtimestamp(t).astimezone()
        return "%d = %s UTC = %s local" % (
            t, utc.strftime("%Y-%m-%d %H:%M:%S"), loc.strftime("%Y-%m-%d %H:%M:%S %Z"))
    except (OverflowError, OSError, ValueError):
        return "%d (out of range)" % t


def print_record(idx, rec, offset=None, pcores=None, out=None):
    w = (out or sys.stdout).write
    head = "=== record %d" % idx
    if offset is not None:
        head += " (file offset 0x%x)" % offset
    w(head + " ===\n")
    cpu = rec["extcpu"]
    ctype = ""
    if pcores is not None:
        ctype = "  [%s]" % ("P-core" if cpu in pcores else "E-core")
    w("cpu        : %d%s  (legacy 8-bit cpu field=%d)\n" % (cpu, ctype, rec["cpu"]))
    w("apicid     : 0x%x (%d)   socket: %d\n" % (rec["apicid"], rec["apicid"], rec["socketid"]))
    hint = BANK_HINTS.get(rec["bank"], "unit not publicly documented for this CPU (uncore/SoC bank?)")
    w("bank       : %d  -> hint: %s\n" % (rec["bank"], hint))
    w("status     : 0x%016x\n" % rec["status"])
    for line in decode_status(rec["status"], rec["mcgcap"] if rec["mcgcap"] else None):
        w("  " + line + "\n")
    addrv, miscv = bit(rec["status"], 58), bit(rec["status"], 59)
    w("addr       : 0x%016x%s\n" % (rec["addr"], "" if addrv else "  (ADDRV=0: not valid)"))
    w("misc       : 0x%016x%s\n" % (rec["misc"], "" if miscv else "  (MISCV=0: not valid)"))
    if miscv:
        w("  " + decode_misc(rec["misc"]) + "\n")
    w("mcgstatus  : 0x%x  %s\n" % (rec["mcgstatus"], decode_mcgstatus(rec["mcgstatus"])))
    if not bit(rec["mcgstatus"], 2):
        w("  MCIP=0: record was not taken inside a #MC handler (polled / left over from"
          " before reset / CMCI)\n")
    w("mcgcap     : 0x%x  %s\n" % (rec["mcgcap"], decode_mcgcap(rec["mcgcap"])))
    ipnote = ""
    if not rec["ip"]:
        ipnote = "  (0: not captured - normal for polled/boot-time records)"
    elif not bit(rec["mcgstatus"], 1):
        ipnote = "  (!INEXACT!: EIPV=0, ip is not the faulting instruction)"
    w("ip         : 0x%016x%s\n" % (rec["ip"], ipnote))
    w("cs         : 0x%02x  (ring %d)\n" % (rec["cs"], rec["cs"] & 3))
    w("tsc        : 0x%x (%d)%s\n" % (rec["tsc"], rec["tsc"],
                                     "" if rec["tsc"] else "  (0: not recorded - boot-time poll)"))
    w("time       : %s\n" % fmt_time(rec["time"]))
    w("             (time = when the kernel logged the record, NOT when the error happened;\n"
      "              for boot-time leftovers it is the boot time)\n")
    w("cpuid      : 0x%08x  %s   vendor=%d (%s)\n" % (
        rec["cpuid"], decode_cpuid(rec["cpuid"], rec["cpuvendor"]), rec["cpuvendor"],
        X86_VENDORS.get(rec["cpuvendor"], "?")))
    w("microcode  : 0x%x\n" % rec["microcode"])
    w("ppin       : 0x%x%s\n" % (rec["ppin"], "" if rec["ppin"] else "  (0: PPIN not available/enabled)"))
    w("severity   : %d (%s)   inject_flags: 0x%x   finished: %d\n" % (
        rec["severity"], SEVERITIES.get(rec["severity"], "?"), rec["inject_flags"],
        rec["finished"]))
    kf = [n for b, n in KFLAGS if bit(rec["kflags"], b)]
    if rec["kflags"]:
        w("kflags     : 0x%x %s  (UNEXPECTED: dev-mcelog.c stores 0 here - wrong record "
          "length or not a /dev/mcelog capture?)\n" % (rec["kflags"], " ".join(kf)))
    else:
        w("kflags     : 0x0 (dev-mcelog.c always stores 0 here)\n")
    if rec["synd"] or rec["ipid"]:
        w("synd/ipid  : 0x%x / 0x%x (AMD SMCA only)\n" % (rec["synd"], rec["ipid"]))
    if rec["pad"]:
        w("pad        : 0x%x (expected 0)\n" % rec["pad"])
    w("\n")


def summary_line(idx, rec):
    _, text = decode_mcacod(rec["status"] & 0xFFFF)
    return "#%d cpu=%d apic=0x%x bank=%d status=0x%016x %s%s%s mscod=0x%04x mcacod=0x%04x [%s]" % (
        idx, rec["extcpu"], rec["apicid"], rec["bank"], rec["status"],
        "UC " if bit(rec["status"], 61) else "CE ",
        "PCC " if bit(rec["status"], 57) else "",
        "OVER " if bit(rec["status"], 62) else "",
        bits(rec["status"], 31, 16), rec["status"] & 0xFFFF, text)


def decode_binary(path, reclen, pcores, show_invalid):
    with open(path, "rb") as fh:
        data = fh.read()
    print("file: %s  size: %d bytes  record length: %d" % (path, len(data), reclen))
    if len(data) == 0:
        print("EMPTY FILE: /dev/mcelog held no records when it was read "
              "(the buffer lives in RAM only: it is lost at every reset and "
              "emptied by every read).")
        return 0
    if data[:12] == b"MACHINECHECK":
        print("NOTE: file starts with the MCE_LOG_SIGNATURE 'MACHINECHECK': this looks like a "
              "struct mce_log_buffer memory dump (signature[12], len, next, flags, recordlen), "
              "not a /dev/mcelog read; skipping the 28-byte header.")
        hlen, hnext, hflags, hreclen = struct.unpack_from("<4I", data, 12)
        print("  len=%d next=%d flags=0x%x recordlen=%d" % (hlen, hnext, hflags, hreclen))
        data = data[28:]
        if hreclen:
            reclen = hreclen
    if reclen < MCE_SIZE:
        print("WARNING: record length %d < %d; fields beyond the record are shown as 0"
              % (reclen, MCE_SIZE))
    if len(data) % reclen:
        print("WARNING: size is not a multiple of %d (%d trailing bytes ignored); "
              "wrong --reclen or a truncated capture?" % (reclen, len(data) % reclen))
    n = len(data) // reclen
    recs = []
    for i in range(n):
        chunk = data[i * reclen:(i + 1) * reclen]
        chunk = (chunk + b"\0" * MCE_SIZE)[:MCE_SIZE]
        rec = dict(zip(MCE_FIELDS, struct.unpack(MCE_FMT, chunk)))
        recs.append((i, i * reclen, rec))
    print("records in file: %d\n" % n)
    shown = 0
    for i, off, rec in recs:
        if not any(rec.values()):
            if show_invalid:
                print("=== record %d (file offset 0x%x): all zero ===\n" % (i, off))
            continue
        if not rec["finished"] and not show_invalid:
            print("=== record %d: finished=0 (skipped; use --all to show) ===\n" % i)
            continue
        print_record(i, rec, off, pcores)
        shown += 1
    print("--- summary (%d decoded) ---" % shown)
    for i, off, rec in recs:
        if any(rec.values()) and (rec["finished"] or show_invalid):
            print(summary_line(i, rec))
    return 0


# "mce=print_all" / __print_mce() output, arch/x86/kernel/cpu/mce/core.c (v6.14):
#   [Hardware Error]: CPU %d: Machine Check%s: %Lx Bank %d: %016Lx
#   [Hardware Error]: RIP%s %02x:<%016Lx> {sym}
#   [Hardware Error]: TSC %llx ADDR %llx MISC %llx PPIN %llx
#   [Hardware Error]: PROCESSOR %u:%x TIME %llu SOCKET %u APIC %x microcode %x
RE_HEAD = re.compile(r"CPU (\d+): Machine Check( Exception)?: ([0-9a-fA-F]+) Bank (\d+): ([0-9a-fA-F]{16})")
RE_RIP = re.compile(r"RIP( !INEXACT!)? ([0-9a-fA-F]{2}):<([0-9a-fA-F]{16})>")
RE_TSC = re.compile(r"TSC ([0-9a-fA-F]+)")
RE_ADDR = re.compile(r"ADDR ([0-9a-fA-F]+)")
RE_MISC = re.compile(r"MISC ([0-9a-fA-F]+)")
RE_PPIN = re.compile(r"PPIN ([0-9a-fA-F]+)")
RE_PROC = re.compile(r"PROCESSOR (\d+):([0-9a-fA-F]+) TIME (\d+) SOCKET (\d+) APIC ([0-9a-fA-F]+) microcode ([0-9a-fA-F]+)")


def decode_text(path, pcores):
    recs = []
    cur = None
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            m = RE_HEAD.search(line)
            if m:
                cur = dict.fromkeys(MCE_FIELDS, 0)
                cur["extcpu"] = cur["cpu"] = int(m.group(1))
                cur["mcgstatus"] = int(m.group(3), 16)
                cur["bank"] = int(m.group(4))
                cur["status"] = int(m.group(5), 16)
                cur["finished"] = 1
                cur["_src"] = line.strip()
                recs.append(cur)
                continue
            if cur is None or "Hardware Error" not in line:
                continue
            m = RE_RIP.search(line)
            if m:
                cur["cs"] = int(m.group(2), 16)
                cur["ip"] = int(m.group(3), 16)
            m = RE_TSC.search(line)
            if m:
                cur["tsc"] = int(m.group(1), 16)
                for key, rx in (("addr", RE_ADDR), ("misc", RE_MISC), ("ppin", RE_PPIN)):
                    mm = rx.search(line)
                    if mm:
                        cur[key] = int(mm.group(1), 16)
            m = RE_PROC.search(line)
            if m:
                cur["cpuvendor"] = int(m.group(1))
                cur["cpuid"] = int(m.group(2), 16)
                cur["time"] = int(m.group(3))
                cur["socketid"] = int(m.group(4))
                cur["apicid"] = int(m.group(5), 16)
                cur["microcode"] = int(m.group(6), 16)
                cur = None
    print("file: %s  machine-check records found in text: %d\n" % (path, len(recs)))
    for i, rec in enumerate(recs):
        print("source line: " + rec.pop("_src"))
        print_record(i, rec, None, pcores)
    print("NOTE: text records carry no mcgcap/severity; the UCR class assumes SER_P=1.")
    return 0


class _CMce(ctypes.Structure):
    """Native-ABI mirror of struct mce; used only to cross-check MCE_FMT."""
    _fields_ = [
        ("status", ctypes.c_uint64), ("misc", ctypes.c_uint64), ("addr", ctypes.c_uint64),
        ("mcgstatus", ctypes.c_uint64), ("ip", ctypes.c_uint64), ("tsc", ctypes.c_uint64),
        ("time", ctypes.c_uint64),
        ("cpuvendor", ctypes.c_uint8), ("inject_flags", ctypes.c_uint8),
        ("severity", ctypes.c_uint8), ("pad", ctypes.c_uint8),
        ("cpuid", ctypes.c_uint32),
        ("cs", ctypes.c_uint8), ("bank", ctypes.c_uint8), ("cpu", ctypes.c_uint8),
        ("finished", ctypes.c_uint8),
        ("extcpu", ctypes.c_uint32), ("socketid", ctypes.c_uint32), ("apicid", ctypes.c_uint32),
        ("mcgcap", ctypes.c_uint64), ("synd", ctypes.c_uint64), ("ipid", ctypes.c_uint64),
        ("ppin", ctypes.c_uint64),
        ("microcode", ctypes.c_uint32),
        ("kflags", ctypes.c_uint64),
    ]


def selftest():
    ok = True

    def check(cond, what):
        nonlocal ok
        print("%s  %s" % ("ok  " if cond else "FAIL", what))
        ok = ok and cond

    check(MCE_SIZE == 128, "struct format size == 128 (got %d)" % MCE_SIZE)
    check(ctypes.sizeof(_CMce) == 128, "ctypes native-ABI sizeof(struct mce) == 128 (got %d)"
          % ctypes.sizeof(_CMce))
    expect = {"status": 0, "misc": 8, "addr": 16, "mcgstatus": 24, "ip": 32, "tsc": 40,
              "time": 48, "cpuvendor": 56, "inject_flags": 57, "severity": 58, "pad": 59,
              "cpuid": 60, "cs": 64, "bank": 65, "cpu": 66, "finished": 67, "extcpu": 68,
              "socketid": 72, "apicid": 76, "mcgcap": 80, "synd": 88, "ipid": 96,
              "ppin": 104, "microcode": 112, "kflags": 120}
    for name, off in expect.items():
        got = getattr(_CMce, name).offset
        check(got == off, "offsetof(%s) == %d (ctypes says %d)" % (name, off, got))
    # struct format must unpack a ctypes-built record identically
    c = _CMce()
    for i, name in enumerate(MCE_FIELDS):
        setattr(c, name, (i + 1) & 0xFF)
    rec = dict(zip(MCE_FIELDS, struct.unpack(MCE_FMT, bytes(c))))
    check(all(rec[n] == ((i + 1) & 0xFF) for i, n in enumerate(MCE_FIELDS)),
          "struct.unpack(MCE_FMT) agrees with the ctypes layout for every field")
    cases = (
        (0x0000, "No error"), (0x0001, "Unclassified"), (0x0002, "Microcode ROM parity"),
        (0x0003, "External error"), (0x0004, "FRC"), (0x0005, "Internal parity error"),
        (0x0006, "SMM handler"), (0x0400, "Internal timer error"),
        (0x0401, "Internal unclassified"), (0x07FF, "Internal unclassified"),
        (0x0E0B, "I/O error"),
        (0x000D, "Generic cache hierarchy error, level L1"),
        (0x0014, "TLB error: D (data), level L0"),
        (0x0011, "TLB error: I (instruction), level L1"),
        (0x0135, "Cache hierarchy error: DRD (data read), D (data) cache, level L1"),
        (0x0151, "Cache hierarchy error: IRD (instruction fetch), I (instruction) cache, level L1"),
        (0x0150, "IRD (instruction fetch), I (instruction) cache, level L0"),
        (0x017A, "EVICT, G (generic) cache, level L2"),
        (0x110A, "Cache hierarchy error: ERR (generic error), G (generic) cache, level L2; F=1"),
        (0x0090, "Memory controller error: RD (memory read error), channel 0"),
        (0x00CF, "Memory controller error: MS (memory scrubbing error), channel not specified"),
        (0x0291, "Extended memory error: RD (memory read error), channel 1"),
        (0x0E0F, "Bus/interconnect error: participation generic, no timeout, request ERR"),
        (0x0800, "Bus/interconnect error: participation SRC"),
        (0x090F, "TIMEOUT"),
        (0x2000, "Unrecognised"),
    )
    for code, want in cases:
        _, got = decode_mcacod(code)
        check(want in got, "MCACOD 0x%04x -> %s" % (code, got))
    lines = "\n".join(decode_status(0xBE000000E1840400, 0x0F000C20))
    check("processor context corrupt" in lines and "0xe184" in lines
          and "Internal timer error" in lines,
          "status 0xbe000000e1840400 -> UC/PCC, MSCOD 0xe184, internal timer error")
    check("SRAR" in "\n".join(decode_status(0xBD80000000100134, 0x0F000C20)),
          "status 0xbd80000000100134 -> SRAR")
    check("UCNA" in "\n".join(decode_status(0xAC00000000000179 | (1 << 63), 0x0F000C20)),
          "UC=1 PCC=0 S=0 AR=0 -> UCNA")
    check("family 0x6 model 0xc6 stepping 2 (Arrow Lake-S)" == decode_cpuid(0xC0662),
          "cpuid 0xc0662 -> " + decode_cpuid(0xC0662))
    print("SELFTEST %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Decode struct mce records read from /dev/mcelog (Linux v6.14 layout).")
    ap.add_argument("file", nargs="?", help="binary capture of /dev/mcelog (or log text with --text)")
    ap.add_argument("--reclen", type=int, default=MCE_SIZE,
                    help="record length in bytes (ioctl MCE_GET_RECORD_LEN; default %d)" % MCE_SIZE)
    ap.add_argument("--all", action="store_true", help="also show all-zero / unfinished records")
    ap.add_argument("--pcores", metavar="LIST",
                    help="Linux CPU list of the P-cores, e.g. 0-7, to label records P-core/E-core")
    ap.add_argument("--text", action="store_true",
                    help="FILE is kernel log text containing '[Hardware Error]: CPU n: Machine Check' lines")
    ap.add_argument("--status", metavar="HEX", help="decode a single IA32_MCi_STATUS value")
    ap.add_argument("--bank", type=int, default=None)
    ap.add_argument("--mcgcap", metavar="HEX", default=None)
    ap.add_argument("--misc", metavar="HEX", default=None)
    ap.add_argument("--addr", metavar="HEX", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    pcores = parse_cpulist(args.pcores) if args.pcores else None
    if args.status:
        status = int(args.status, 16)
        mcgcap = int(args.mcgcap, 16) if args.mcgcap else None
        print("status     : 0x%016x" % status)
        if args.bank is not None:
            print("bank       : %d  -> hint: %s" % (
                args.bank, BANK_HINTS.get(args.bank, "unit not publicly documented")))
        for line in decode_status(status, mcgcap):
            print("  " + line)
        if args.addr:
            print("addr       : 0x%016x%s" % (int(args.addr, 16),
                                            "" if bit(status, 58) else "  (ADDRV=0)"))
        if args.misc:
            print("misc       : 0x%016x  %s" % (int(args.misc, 16), decode_misc(int(args.misc, 16))))
        return 0
    if not args.file:
        ap.print_usage(sys.stderr)
        return 2
    if args.text:
        return decode_text(args.file, pcores)
    return decode_binary(args.file, args.reclen, pcores, args.all)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
