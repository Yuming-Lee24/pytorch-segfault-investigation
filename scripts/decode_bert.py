#!/usr/bin/env python3
"""Walk an ACPI Boot Error Region (the content of /sys/firmware/acpi/tables/data/BERT).

Usage:
    decode_bert.py FILE [--dump N] [--full] [-v] [--extract DIR]

FILE may be
  * the raw boot error region  (cp /sys/firmware/acpi/tables/data/BERT FILE),
  * the 48-byte ACPI BERT table (/sys/firmware/acpi/tables/BERT) - header is printed,
  * the table immediately followed by the region (cat tables/BERT tables/data/BERT),
  * a region prefixed with the 4 ASCII bytes "BERR" (the format Intel's iclg accepts).

For every Generic Error Status Block and every Generic Error Data Entry it prints
severity, section GUID (with a name where known), FRU text and the lengths, and
hexdumps the first N (default 256) payload bytes.  Extra decoding:
  * IA32/X64 Processor Error sections: error-info "check information" and MSR
    context dumps (IA32_MCi_CTL/STATUS/ADDR/MISC are named and STATUS is decoded);
  * Processor Generic sections;
  * Firmware Error Record Reference sections; when the record identifier is the
    Intel CrashLog GUID 8f87f311-c998-4d9e-a0c4-6065518c4f6d the payload is walked
    as a CrashLog region (record headers per github.com/intel/crashlog lib/src/header.rs)
    and the publicly documented record layouts are decoded:
      - MCA record of Arrow Lake (product 0x7F rev 1, product 0x98 rev 2):
        per core, banks 0-3, {status, addr, misc};
      - PMC_RST record rev 1 of product 0x3F (MTL/SS) and 0x66 (MTL/IOEP):
        global-reset / host-partition-reset cause bits.

IMPORTANT: Linux (drivers/acpi/apei/bert.c, bert_print_all) writes 0 to the
block_status field of every status block it has processed at boot, and the sysfs
file is a live view of that memory.  A block_status of 0 in front of an otherwise
valid block is therefore normal and is NOT treated as "end of records" here.

Only the python3 standard library is used.
"""

import argparse
import os
import struct
import sys
import uuid

# --------------------------------------------------------------------------
# GUID tables
# --------------------------------------------------------------------------
SECTION_GUIDS = {
    "9876ccad-47b4-4bdb-b65e-16f193c4f3db": "Processor Generic",
    "dc3ea0b0-a144-4797-b95b-53fa242b6e1d": "Processor Specific: IA32/X64",
    "e429faf1-3cb7-11d4-bca7-0080c73c8881": "Processor Specific: IPF",
    "e19e3d16-bc11-11e4-9caa-c2051d5d46b0": "Processor Specific: ARM",
    "a5bc1114-6f64-4ede-b863-3e83ed7c83b1": "Platform Memory",
    "61ec04fc-48e6-d813-25c9-8daa44750b12": "Platform Memory 2",
    "d995e954-bbc1-430f-ad91-b44dcb3c6f35": "PCI Express",
    "81212a96-09ed-4996-9471-8d729c8e69ed": "Firmware Error Record Reference",
    "c5753963-3b84-4095-bf78-eddad3f9c9dd": "PCI/PCI-X Bus",
    "eb5e4685-ca66-4769-b6a2-26068b001326": "PCI Component/Device",
    "5b51fef7-c79d-4434-8f1b-aa62de3e2c64": "DMAR Generic",
    "71761d37-32b2-45cd-a7d0-b0fedd93e8cf": "Intel VT-d specific DMAR",
    "036f84e1-7f37-428c-a79e-575fdfaa84ec": "IOMMU specific DMAR",
    "91335ef6-ebfb-4478-a6a6-88b728cf75d7": "CCIX PER Log",
    "80b9efb4-52b5-4de3-a777-68784b771048": "CXL Protocol Error",
    "fbcd0a77-c260-417f-85a9-088b1621eba6": "CXL General Media Event",
    "601dcbb3-9c06-4eab-b8af-4e9bfb5c9624": "CXL DRAM Event",
    "fe927475-dd59-4339-a586-79bab113b774": "CXL Memory Module Event",
}
GUID_PROC_GENERIC = "9876ccad-47b4-4bdb-b65e-16f193c4f3db"
GUID_PROC_IA = "dc3ea0b0-a144-4797-b95b-53fa242b6e1d"
GUID_MEM = "a5bc1114-6f64-4ede-b863-3e83ed7c83b1"
GUID_FW_ERR = "81212a96-09ed-4996-9471-8d729c8e69ed"
GUID_CRASHLOG = "8f87f311-c998-4d9e-a0c4-6065518c4f6d"   # Intel CrashLog record identifier

IA_ERR_TYPES = {
    "a55701f5-e3ef-43de-ac72-249b573fad2c": "cache error",
    "fc06b535-5e1f-4562-9f25-0a3b9adb63c3": "TLB error",
    "1cf3f8b3-c5b1-49a2-aa59-5eef92ffa63c": "bus error",
    "48ab7f57-dc34-4f6c-a7d3-b0b5b0a74314": "micro-architectural (MS) error",
}

SEVERITY = {0: "recoverable (also called correctable/non-fatal)", 1: "fatal",
            2: "corrected", 3: "informational/none"}

ENTRY_FLAGS = ((0, "Primary"), (1, "ContainmentWarning"), (2, "Reset"),
               (3, "ErrorThresholdExceeded"), (4, "ResourceNotAccessible"),
               (5, "LatentError"), (6, "Propagated"), (7, "Overflow"))


def bit(v, n):
    return (v >> n) & 1


def bits(v, hi, lo):
    return (v >> lo) & ((1 << (hi - lo + 1)) - 1)


def guid_at(data, off):
    chunk = data[off:off + 16]
    if len(chunk) < 16:
        return "(truncated)"
    return str(uuid.UUID(bytes_le=bytes(chunk)))


def u8(data, off):
    return data[off] if off < len(data) else 0


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0] if off + 2 <= len(data) else 0


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0] if off + 4 <= len(data) else 0


def u64(data, off):
    return struct.unpack_from("<Q", data, off)[0] if off + 8 <= len(data) else 0


def cstr(raw):
    raw = bytes(raw).split(b"\0", 1)[0]
    return "".join(chr(c) if 32 <= c < 127 else "." for c in raw)


def hexdump(data, limit=256, indent="    ", base=0):
    out = []
    shown = data[:limit] if limit is not None else data
    prev = None
    skipping = False
    for i in range(0, len(shown), 16):
        row = shown[i:i + 16]
        if row == prev and len(row) == 16:
            if not skipping:
                out.append(indent + "*")
                skipping = True
            continue
        skipping = False
        prev = row
        hx = " ".join("%02x" % b for b in row[:8]) + "  " + " ".join("%02x" % b for b in row[8:])
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        out.append("%s%08x  %-49s |%s|" % (indent, base + i, hx, asc))
    if limit is not None and len(data) > limit:
        out.append("%s... (%d of %d bytes shown; use --full or --dump N)" % (indent, limit, len(data)))
    return "\n".join(out)


def bcd(b):
    return (b >> 4) * 10 + (b & 0xF)


def fmt_timestamp(raw):
    """ACPI/UEFI CPER timestamp: sec, min, hour, flags, day, month, year, century (BCD)."""
    if len(raw) < 8 or not any(raw):
        return "0 (not set)"
    sec, mn, hr, fl, day, mon, yr, cen = raw[:8]
    return "%02d%02d-%02d-%02d %02d:%02d:%02d (%s; firmware RTC time, raw %s)" % (
        bcd(cen), bcd(yr), bcd(mon), bcd(day), bcd(hr), bcd(mn), bcd(sec),
        "precise" if fl & 1 else "imprecise", bytes(raw[:8]).hex())


# --------------------------------------------------------------------------
# IA32_MCi_STATUS decoding (compact copy of decode_mcelog.py so that this file
# stays self-contained) - SDM Vol. 3B "Interpreting the MCA Error Codes"
# --------------------------------------------------------------------------
_TT = {0: "I", 1: "D", 2: "G", 3: "resv"}
_LL = {0: "L0", 1: "L1", 2: "L2", 3: "LG"}
_RRRR = {0: "ERR", 1: "RD", 2: "WR", 3: "DRD", 4: "DWR", 5: "IRD", 6: "PREFETCH",
         7: "EVICT", 8: "SNOOP"}
_PP = {0: "SRC", 1: "RES", 2: "OBS", 3: "generic"}
_II = {0: "M", 1: "resv", 2: "IO", 3: "other"}
_MMM = {0: "GEN", 1: "RD", 2: "WR", 3: "AC", 4: "MS"}
_SIMPLE = {0x0000: "No error", 0x0001: "Unclassified", 0x0002: "Microcode ROM parity error",
           0x0003: "External error", 0x0004: "FRC error", 0x0005: "Internal parity error",
           0x0006: "SMM handler code access violation", 0x0400: "Internal timer error",
           0x0E0B: "I/O error"}


def decode_mcacod(code):
    code &= 0xFFFF
    if code in _SIMPLE:
        return _SIMPLE[code]
    if code & 0xFC00 == 0x0400:
        return "Internal unclassified error (sub-code 0x%03x)" % (code & 0x3FF)
    f = "; F=1" if bit(code, 12) else ""
    c = code & 0xEFFF
    if c & 0xFFFC == 0x000C:
        return "Generic cache hierarchy error, level %s%s" % (_LL[c & 3], f)
    if c & 0xFFF0 == 0x0010:
        return "TLB error: %sTLB level %s%s" % (_TT[bits(c, 3, 2)], _LL[c & 3], f)
    if c & 0xFF80 == 0x0080:
        return "Memory controller error: %s, channel %s%s" % (
            _MMM.get(bits(c, 6, 4), "resv"), "n/s" if c & 0xF == 0xF else c & 0xF, f)
    if c & 0xFF00 == 0x0100:
        return "Cache hierarchy error: %s, %sCACHE level %s%s" % (
            _RRRR.get(bits(c, 7, 4), "resv"), _TT[bits(c, 3, 2)], _LL[c & 3], f)
    if c & 0xFF80 == 0x0280:
        return "Extended memory error: %s, channel %s%s" % (
            _MMM.get(bits(c, 6, 4), "resv"), "n/s" if c & 0xF == 0xF else c & 0xF, f)
    if c & 0xF800 == 0x0800:
        return "Bus/interconnect error: PP=%s %s RRRR=%s II=%s level %s%s" % (
            _PP[bits(c, 10, 9)], "TIMEOUT" if bit(c, 8) else "no-timeout",
            _RRRR.get(bits(c, 7, 4), "resv"), _II[bits(c, 3, 2)], _LL[c & 3], f)
    return "Unrecognised MCACOD 0x%04x" % code


def decode_status_line(status):
    names = (("VAL", 63), ("OVER", 62), ("UC", 61), ("EN", 60), ("MISCV", 59),
             ("ADDRV", 58), ("PCC", 57), ("S", 56), ("AR", 55))
    flags = " ".join(n for n, b in names if bit(status, b)) or "-"
    return "[%s] MSCOD=0x%04x MCACOD=0x%04x (%s)" % (
        flags, bits(status, 31, 16), status & 0xFFFF, decode_mcacod(status))


def msr_name(addr):
    fixed = {0x179: "IA32_MCG_CAP", 0x17A: "IA32_MCG_STATUS", 0x17B: "IA32_MCG_CTL",
             0x4D0: "IA32_MCG_EXT_CTL"}
    if addr in fixed:
        return fixed[addr], None
    if 0x400 <= addr < 0x480:
        bank, reg = divmod(addr - 0x400, 4)
        return "IA32_MC%d_%s" % (bank, ("CTL", "STATUS", "ADDR", "MISC")[reg]), reg
    if 0x280 <= addr < 0x2A0:
        return "IA32_MC%d_CTL2" % (addr - 0x280), None
    if 0xC0002000 <= addr < 0xC0002400:
        bank, reg = divmod(addr - 0xC0002000, 16)
        names = {0: "CTL", 1: "STATUS", 2: "ADDR", 3: "MISC0", 4: "CONFIG", 5: "IPID",
                 6: "SYND", 8: "DESTAT", 9: "DEADDR"}
        return "AMD_SMCA_MC%d_%s" % (bank, names.get(reg, "REG%x" % reg)), (1 if reg == 1 else None)
    return "MSR", None


# --------------------------------------------------------------------------
# CPER section decoders
# --------------------------------------------------------------------------
def decode_proc_generic(p, pr):
    if len(p) < 192:
        pr("  (section shorter than the 192-byte Processor Generic structure)")
        return
    val = u64(p, 0)
    ptype, isa, etype, op, flags, level = p[8], p[9], p[10], p[11], p[12], p[13]
    pr("  validation_bits: 0x%x" % val)
    if val & 0x1:
        pr("  processor_type: %d (%s)" % (ptype, {0: "IA32/X64", 1: "IA64", 2: "ARM"}.get(ptype, "?")))
    if val & 0x2:
        pr("  processor_isa: %d (%s)" % (isa, {0: "IA32", 1: "IA64", 2: "X64", 3: "ARM A32/T32",
                                                4: "ARM A64"}.get(isa, "?")))
    if val & 0x4:
        names = [n for b, n in ((0, "cache error"), (1, "TLB error"), (2, "bus error"),
                                (3, "micro-architectural error")) if bit(etype, b)]
        pr("  error_type: 0x%02x (%s)" % (etype, ", ".join(names) or "unknown"))
    if val & 0x8:
        pr("  operation: %d (%s)" % (op, {0: "unknown or generic", 1: "data read", 2: "data write",
                                          3: "instruction execution"}.get(op, "?")))
    if val & 0x10:
        names = [n for b, n in ((0, "restartable"), (1, "precise IP"), (2, "overflow"),
                                (3, "corrected")) if bit(flags, b)]
        pr("  flags: 0x%02x (%s)" % (flags, ", ".join(names) or "-"))
    if val & 0x20:
        pr("  level: %d" % level)
    if val & 0x40:
        pr("  cpu_version (CPUID): 0x%016x" % u64(p, 16))
    if val & 0x80:
        pr("  cpu_brand: %s" % cstr(p[24:152]))
    for mask, name, off in ((0x100, "processor_id", 152), (0x200, "target_address", 160),
                            (0x400, "requestor_id", 168), (0x800, "responder_id", 176),
                            (0x1000, "IP", 184)):
        if val & mask:
            pr("  %s: 0x%016x" % (name, u64(p, off)))


def decode_ia_check(err_type, check, pr):
    vb = check & 0xFFFF
    pfx = "      "
    if err_type == "micro-architectural (MS) error":
        if vb & 0x1:
            t = bits(check, 18, 16)
            names = ("No Error", "Unclassified", "Microcode ROM Parity Error", "External Error",
                     "FRC Error", "Internal Unclassified")
            pr(pfx + "Error Type: %d, %s" % (t, names[t] if t < len(names) else "unknown"))
        for mask, name, b in ((0x2, "Processor Context Corrupt", 19), (0x4, "Uncorrected", 20),
                              (0x8, "Precise IP", 21), (0x10, "Restartable IP", 22),
                              (0x20, "Overflow", 23)):
            if vb & mask:
                pr(pfx + "%s: %s" % (name, "true" if bit(check, b) else "false"))
        return
    if vb & 0x1:
        t = bits(check, 17, 16)
        names = ("Instruction", "Data Access", "Generic")
        pr(pfx + "Transaction Type: %d, %s" % (t, names[t] if t < len(names) else "unknown"))
    if vb & 0x2:
        o = bits(check, 21, 18)
        names = ("generic error", "generic read", "generic write", "data read", "data write",
                 "instruction fetch", "prefetch", "eviction", "snoop")
        mx = 9 if err_type == "cache error" else 7
        pr(pfx + "Operation: %d, %s" % (o, names[o] if o < mx else "unknown"))
    if vb & 0x4:
        pr(pfx + "Level: %d" % bits(check, 24, 22))
    for mask, name, b in ((0x8, "Processor Context Corrupt", 25), (0x10, "Uncorrected", 26),
                          (0x20, "Precise IP", 27), (0x40, "Restartable IP", 28),
                          (0x80, "Overflow", 29)):
        if vb & mask:
            pr(pfx + "%s: %s" % (name, "true" if bit(check, b) else "false"))
    if err_type != "bus error":
        return
    if vb & 0x100:
        t = bits(check, 31, 30)
        names = ("Local Processor originated request", "Local Processor responded to request",
                 "Local Processor observed", "Generic")
        pr(pfx + "Participation Type: %d, %s" % (t, names[t]))
    if vb & 0x200:
        pr(pfx + "Time Out: %s" % ("true" if bit(check, 32) else "false"))
    if vb & 0x400:
        t = bits(check, 34, 33)
        names = ("Memory Access", "Reserved", "I/O", "Other Transaction")
        pr(pfx + "Address Space: %d, %s" % (t, names[t]))


IA_CTX_TYPES = ("Unclassified Data", "MSR Registers (Machine Check and other MSRs)",
                "32-bit Mode Execution Context", "64-bit Mode Execution Context",
                "FXSAVE Context", "32-bit Mode Debug Registers (DR0-DR7)",
                "64-bit Mode Debug Registers (DR0-DR7)", "Memory Mapped Registers")


def decode_proc_ia(p, pr, dump_limit):
    if len(p) < 64:
        pr("  (section shorter than the 64-byte IA32/X64 header)")
        return
    val = u64(p, 0)
    n_err = bits(val, 7, 2)
    n_ctx = bits(val, 13, 8)
    pr("  validation_bits: 0x%x (LAPIC_ID valid=%d, CPUID valid=%d, error-info structs=%d, "
       "context structs=%d)" % (val, bit(val, 0), bit(val, 1), n_err, n_ctx))
    if val & 1:
        pr("  Local APIC_ID: 0x%x" % u64(p, 8))
    if val & 2:
        regs = struct.unpack_from("<4Q", p, 16)
        eax = regs[0] & 0xFFFFFFFF
        model = ((eax >> 4) & 0xF) | (((eax >> 16) & 0xF) << 4)
        pr("  CPUID(1): EAX=0x%08x EBX=0x%08x ECX=0x%08x EDX=0x%08x  (family 0x%x model 0x%x "
           "stepping %d)" % (eax, regs[1] & 0xFFFFFFFF, regs[2] & 0xFFFFFFFF,
                             regs[3] & 0xFFFFFFFF, (eax >> 8) & 0xF, model, eax & 0xF))
    off = 64
    for i in range(n_err):
        if off + 64 > len(p):
            pr("  Error Information Structure %d: TRUNCATED (section too short)" % i)
            return
        g = guid_at(p, off)
        etype = IA_ERR_TYPES.get(g, "unknown")
        ev, check, target, req, resp, ip = struct.unpack_from("<6Q", p, off + 16)
        pr("  Error Information Structure %d:" % i)
        pr("    Error Structure Type: %s (%s)" % (etype, g))
        pr("    validation_bits: 0x%x" % ev)
        if ev & 0x1:
            pr("    Check Information: 0x%016x" % check)
            if etype != "unknown":
                decode_ia_check(etype, check, pr)
        if ev & 0x2:
            pr("    Target Identifier: 0x%016x" % target)
        if ev & 0x4:
            pr("    Requestor Identifier: 0x%016x" % req)
        if ev & 0x8:
            pr("    Responder Identifier: 0x%016x" % resp)
        if ev & 0x10:
            pr("    Instruction Pointer: 0x%016x" % ip)
        off += 64
    for i in range(n_ctx):
        if off + 16 > len(p):
            pr("  Context Information Structure %d: TRUNCATED (section too short)" % i)
            return
        ctype, size, msr_addr, mm_addr = struct.unpack_from("<HHIQ", p, off)
        pr("  Context Information Structure %d:" % i)
        pr("    Register Context Type: %d (%s)" % (
            ctype, IA_CTX_TYPES[ctype] if ctype < len(IA_CTX_TYPES) else "unknown"))
        pr("    Register Array Size: 0x%04x" % size)
        arr = p[off + 16:off + 16 + size]
        if len(arr) < size:
            pr("    WARNING: register array truncated (%d of %d bytes present)" % (len(arr), size))
        if ctype == 1:
            pr("    MSR Address: 0x%08x" % msr_addr)
            for j in range(len(arr) // 8):
                v = u64(arr, j * 8)
                name, reg = msr_name(msr_addr + j)
                line = "      0x%08x %-18s = 0x%016x" % (msr_addr + j, name, v)
                if reg == 1:
                    line += "  " + decode_status_line(v)
                pr(line)
        else:
            if ctype == 7:
                pr("    MM Register Address: 0x%016x" % mm_addr)
            pr("    Register Array:")
            pr(hexdump(arr, dump_limit, "      "))
        off += (16 + size + 15) & ~15


def decode_mem(p, pr):
    if len(p) < 73:
        pr("  (section shorter than the Platform Memory structure)")
        return
    val = u64(p, 0)
    pr("  validation_bits: 0x%x" % val)
    if val & 0x1:
        pr("  error_status: 0x%016x" % u64(p, 8))
    if val & 0x2:
        pr("  physical_address: 0x%016x" % u64(p, 16))
    if val & 0x4:
        pr("  physical_address_mask: 0x%016x" % u64(p, 24))
    names = ("node", "card", "module", "bank", "device", "row", "column", "bit_position")
    for i, name in enumerate(names):
        if val & (0x8 << i):
            pr("  %s: %d" % (name, u16(p, 32 + 2 * i)))
    if val & 0x4000:
        t = p[72]
        types = ("unknown", "no error", "single-bit ECC", "multi-bit ECC", "single-symbol chipkill ECC",
                 "multi-symbol chipkill ECC", "master abort", "target abort", "parity error",
                 "watchdog timeout", "invalid address", "mirror Broken", "memory sparing",
                 "scrub corrected error", "scrub uncorrected error", "physical memory map-out event")
        pr("  error_type: %d (%s)" % (t, types[t] if t < len(types) else "?"))


# --------------------------------------------------------------------------
# Intel CrashLog region (payload of a Firmware Error Record with GUID_CRASHLOG)
# Header layout: github.com/intel/crashlog lib/src/header.rs, errata.rs, region.rs
# --------------------------------------------------------------------------
CL_RECORD_TYPES = {0x01: "PMC", 0x02: "PMC_FW_TRACE", 0x03: "PUNIT", 0x04: "PCORE",
                   0x06: "ECORE", 0x08: "UNCORE", 0x11: "PMC_TRACE", 0x16: "TCSS",
                   0x17: "PMC_RST", 0x19: "PCODE", 0x1C: "CRASHLOG_AGENT", 0x3D: "BOX",
                   0x3E: "MCA"}
# product ids taken from lib/collateral/*/target_info.json and lib/src/errata.rs
CL_PRODUCTS = {0x7F: "ARL/CDS (arrowlake, model 0xC6)", 0x98: "ARL/CDH (arrowlake)",
               0x3F: "MTL/SS (meteorlake)", 0x3D: "MTL/NS (meteorlake)",
               0x66: "MTL/IOEP (meteorlake)", 0x2F: "GNR/SP", 0x82: "SRF/SP",
               0x85: "CGC", 0x8E: "CWF/SP", 0x5D: "BMG", 0x5E: "BMG", 0x5F: "BMG", 0xB6: "CRI"}
CL_LEGACY_SERVER = (0x2F, 0x82, 0x8E)
CL_LEGACY_GPU = (0x5D, 0x5E, 0x5F, 0xB6)

# PMC_RST revision 1 register bit names
# (lib/collateral/MTL/{SS,IOEP}/all/green/crashlog/decode-defs/PMC_RST/1/layout.csv)
_GBLRST_SS = {0: "secure_policy_err", 2: "pmc_unc_err", 3: "socs_thrm", 4: "me_pbo",
              5: "socn_thrm", 6: "megbl", 7: "lt_reset", 8: "pmc_wdt", 9: "me_wdt",
              10: "pmc_fw", 11: "pchpwr_flr", 12: "syspwr_flr", 14: "mia_uxs_err",
              15: "mia_ux_err", 16: "cpu_thrm_wdt", 17: "me_unc_err", 18: "adr_gpio",
              19: "ocwdt_noicc", 20: "ocwdt_icc", 21: "cse_hec_unc_err",
              22: "pmc_sram_unc_err", 23: "pmc_irom_parity", 24: "pmc_rf_fusa_err",
              25: "compute_thrm", 26: "gfx_thrm", 27: "base_thrm", 28: "ioe_thrm",
              29: "reset_sync_b", 31: "ioe_grst_trigger"}
_GBLRST_IOEP = {1: "pbo", 2: "pmc_unc_err", 3: "pch_thrm", 4: "me_pbo", 5: "cpu_thrm",
                6: "megbl", 7: "lt_reset", 8: "pmc_wdt", 9: "me_wdt", 10: "pmc_fw",
                11: "pchpwr_flr", 12: "syspwr_flr", 14: "mia_uxs_err", 15: "mia_ux_err",
                16: "cpu_thrm_wdt", 17: "me_unc_err", 18: "adr_gpio", 19: "ocwdt_noicc",
                20: "ocwdt_icc", 21: "cse_hec_unc_err", 22: "pmc_sram_unc_err",
                23: "pmc_irom_parity", 24: "pmc_rf_fusa_err", 25: "arc_triple_fault",
                26: "sb_xccm_loader", 31: "soc_pmc_cold_boot_trig"}
_FWGBL = {0: "host_reset_timeout", 1: "sx_entry_timeout", 2: "host_rst_prom", 3: "hsmb_msg",
          4: "pmc_3strike", 6: "pmc_dma_timeout", 8: "espi_type7", 9: "espi_type8",
          10: "fw_gblrst_scratch10", 11: "fw_gblrst_scratch11", 12: "lpm_fw_err",
          13: "bscan_mode", 14: "slp_lvl_rsp_err"}
_FWGBL.update({n: "fw_gblrst_scratch%d" % n for n in range(15, 24)})
_FWGBL_IOEP = dict(_FWGBL)
_FWGBL_IOEP[5] = "pmc_fw_error"
_HOSTPR = {1: "cf9", 2: "sysrst", 3: "ltrst", 6: "tco_wdt", 8: "mi_hr", 9: "hi_prpc",
           10: "mi_hrpd", 11: "ve_wdt", 12: "hsmb_hr", 13: "hsmb_hrpc", 14: "lt_slperr",
           15: "gbl_to_host", 16: "espi_rwopc", 17: "espi_rwpc"}
_PMSTS2 = {0: "eva_l23", 1: "xhci_hrhs", 2: "sp_l23", 3: "smb_srhs", 4: "dmi_l23",
           5: "cpu_s1_ack", 6: "cpu_s345rw_ack", 7: "xck_hrhs", 8: "spi_hrhs",
           9: "exi_state_trans_ack", 10: "smt_rst_ack", 11: "pschs_ack", 12: "pinstop_ack",
           13: "me_hbpd", 14: "crd", 24: "cpuid_pinfo_rsp_to", 25: "me_patch_timeout",
           26: "smt_rsp_data_of", 27: "mac_access_fail", 28: "mb_full", 29: "reg_conflict",
           30: "pipe_slots_empty", 31: "invalid_int"}
PMC_RST_LAYOUTS = {
    (0x3F, 1): (("gblrst_req_0", 8, _GBLRST_SS), ("gblrst_cause_0", 12, _GBLRST_SS),
                ("fw_gblrst_cause_0", 16, _FWGBL), ("host_pr_cause_0", 20, _HOSTPR),
                ("pch_pm_sts2", 24, _PMSTS2)),
    (0x66, 1): (("gblrst_req_0", 8, _GBLRST_IOEP), ("gblrst_cause_0", 12, _GBLRST_IOEP),
                ("fw_gblrst_cause_0", 16, _FWGBL_IOEP), ("pch_pm_sts2", 24, _PMSTS2)),
}
# MCA record layouts that are published: per core 4 banks x {status, addr, misc}
MCA_KNOWN = {(0x7F, 1): 24, (0x98, 2): 14}


def deadbeef_fraction(body):
    n = len(body) // 4
    if not n:
        return 0.0
    cnt = sum(1 for i in range(n) if body[i * 4:i * 4 + 4] == b"\xef\xbe\xad\xde")
    return cnt / n


def decode_cl_mca(rec, product, revision, hdr_size, pr, verbose):
    body = rec[hdr_size:]
    frac = deadbeef_fraction(body)
    if body and frac == 1.0:
        pr("      body is entirely 0xDEADBEEF: MCA data was NOT collected into this record")
        return
    if frac > 0:
        pr("      %.0f%% of the body dwords are 0xDEADBEEF (uncollected fields)" % (frac * 100))
    per_core = 4 * 3 * 8
    known = MCA_KNOWN.get((product, revision))
    if known and len(body) >= known * per_core:
        cores = known
        pr("      layout: PUBLISHED for product 0x%x rev %d: %d cores x banks 0-3 x "
           "{status, addr, misc}" % (product, revision, cores))
    else:
        pr("      layout: NOT PUBLISHED for product 0x%x rev %d (body %d bytes = %d qwords%s)."
           % (product, revision, len(body), len(body) // 8,
              "; = 24 cores x %d qwords" % (len(body) // 192) if body and len(body) % 192 == 0
              else ""))
        pr("      (published layouts: product 0x7f rev 1 and 0x98 rev 2 = per core, banks 0-3 x "
           "{status, addr, misc}).")
        pr("      Heuristic scan for qwords that look like a valid IA32_MCi_STATUS (bit 63 set):")
        hits = 0
        for i in range(len(body) // 8):
            v = u64(body, i * 8)
            if bit(v, 63) and (v & 0xFFFFFFFF) != 0xDEADBEEF and (v >> 32) != 0xDEADBEEF \
                    and v != 0xFFFFFFFFFFFFFFFF:
                pr("        +0x%04x qword %3d: 0x%016x  %s" % (hdr_size + i * 8, i, v,
                                                              decode_status_line(v)))
                hits += 1
        if not hits:
            pr("        (no candidate found)")
        pr("      NOTE: heuristic hits may be addresses or other data; use Intel's iclg to be sure.")
        return
    valid = 0
    for core in range(cores):
        for bank in range(4):
            off = (core * 4 + bank) * 24
            status, addr, misc = struct.unpack_from("<3Q", body, off)
            is_valid = bit(status, 63) and (status & 0xFFFFFFFF) != 0xDEADBEEF
            if is_valid:
                valid += 1
            if is_valid or verbose:
                pr("      core%-2d bank%d: status=0x%016x addr=0x%016x misc=0x%016x" % (
                    core, bank, status, addr, misc))
                if is_valid:
                    pr("                    %s" % decode_status_line(status))
    pr("      MCA banks with VAL=1: %d of %d%s" % (
        valid, cores * 4, "" if verbose or valid else "  (use -v to list all)"))
    pr("      NOTE: 'coreN' is the CrashLog core index; its mapping to Linux CPU numbers / "
       "APIC IDs is not documented publicly.")


def decode_cl_pmc_rst(rec, product, revision, pr):
    layout = PMC_RST_LAYOUTS.get((product, revision))
    if not layout:
        pr("      no published layout embedded for product 0x%x rev %d; raw dwords:" % (
            product, revision))
        pr("      " + " ".join("%08x" % u32(rec, i) for i in range(8, len(rec) - 3, 4)))
        return
    pr("      layout: PUBLISHED PMC_RST rev %d for product 0x%x" % (revision, product))
    for name, off, names in layout:
        if off + 4 > len(rec):
            pr("      %-18s: (beyond end of record)" % name)
            continue
        v = u32(rec, off)
        if v == 0xDEADBEEF:
            pr("      %-18s= 0xdeadbeef (not collected)" % name)
            continue
        setbits = ["%s(bit%d)" % (names.get(b, "undocumented"), b) for b in range(32) if bit(v, b)]
        pr("      %-18s= 0x%08x  %s" % (name, v, " ".join(setbits) if setbits else "(no bit set)"))


def walk_crashlog_region(data, pr, dump_limit, verbose, extract=None, tag=""):
    cursor = 0
    idx = 0
    while cursor + 8 <= len(data):
        version = u32(data, cursor)
        if version in (0, 0xDEADBEEF):
            pr("    [+0x%05x] termination marker 0x%08x" % (cursor, version))
            break
        revision = version & 0xFF
        header_type = (version >> 8) & 0xF
        product = (version >> 12) & 0xFFF
        rtype = (version >> 24) & 0x3F
        cldic = bit(version, 30)
        consumed = bit(version, 31)
        legacy_server = header_type == 0 and product in CL_LEGACY_SERVER
        legacy_gpu = header_type == 0 and product in CL_LEGACY_GPU
        legacy = legacy_server or legacy_gpu
        size_in_bytes = (not legacy) and (
            (rtype == 0x06 and product < 0x96) or
            (rtype == 0x04 and (product < 0x71 or product == 0x85)))
        if legacy:
            rsz, ext = u16(data, cursor + 16), 0
        else:
            rsz, ext = u16(data, cursor + 4), u16(data, cursor + 6)
        size = (rsz + ext) * (1 if size_in_bytes else 4)
        rec = data[cursor:cursor + size] if size else data[cursor:cursor + 32]
        tname = CL_RECORD_TYPES.get(rtype, "UNKNOWN(0x%x)" % rtype)
        pr("    [+0x%05x] CrashLog record %d: %s  rev %d  product 0x%03x %s" % (
            cursor, idx, tname, revision, product,
            "= " + CL_PRODUCTS[product] if product in CL_PRODUCTS else "(product not in table)"))
        pr("      version=0x%08x header_type=%d consumed=%d cldic=%d  size=%d bytes "
           "(record_size=%d ext=%d, unit=%s)" % (
               version, header_type, consumed, cldic, size, rsz, ext,
               "bytes" if size_in_bytes else "dwords"))
        hdr_size = 8
        if legacy:
            hdr_size = 32
            cs = u32(rec, 28)
            pr("      legacy type-0 header: reason=0x%x timestamp=0x%x agent_version=0x%x "
               "completion_status=0x%x collection_complete=%d" % (
                   u32(rec, 4), u64(rec, 8), u32(rec, 20), cs & 0x7FFFFFFF, cs >> 31))
        elif header_type >= 2:
            ts, agent, reason = u64(rec, 8), u32(rec, 16), u32(rec, 20)
            line = "      timestamp=0x%016x agent_version=0x%08x reason=0x%08x" % (ts, agent, reason)
            if header_type == 2:
                hdr_size = 24
            elif header_type == 3:
                cs = u32(rec, 24)
                hdr_size = 28
                line += " completion_status=0x%x collection_complete=%d" % (cs & 0x7FFFFFFF, cs >> 31)
            elif header_type == 4:
                hdr_size = 32
                line += " whoami=0x%x misc=0x%x" % (u32(rec, 24), u32(rec, 28))
            elif header_type == 5:
                cs = u32(rec, 24)
                hdr_size = 32
                line += " completion_status=0x%x collection_complete=%d error_status=0x%x" % (
                    cs & 0x7FFFFFFF, cs >> 31, u32(rec, 28))
            elif header_type == 6:
                n = u16(rec, 26) & 0x7F
                hdr_size = 28 + 4 * n
                line += " die_id=%d socket_id=%d collection_complete=%d completion_status=[%s]" % (
                    u8(rec, 24), u8(rec, 25), u8(rec, 27) >> 7,
                    " ".join("0x%x" % u32(rec, 28 + 4 * k) for k in range(n)))
            else:
                line += " (header type %d not known to this tool; assuming 24-byte header)" % header_type
                hdr_size = 24
            pr(line)
        if size == 0:
            pr("      record has size 0: stopping the walk of this region")
            break
        if cursor + size > len(data):
            pr("      WARNING: truncated record: declared %d bytes, only %d available" % (
                size, len(data) - cursor))
        if rtype == 0x3E:
            decode_cl_mca(rec, product, revision, hdr_size, pr, verbose)
        elif rtype == 0x17:
            decode_cl_pmc_rst(rec, product, revision, pr)
        else:
            frac = deadbeef_fraction(rec[hdr_size:])
            if frac:
                pr("      %.0f%% of the body dwords are 0xDEADBEEF (uncollected)" % (frac * 100))
        if verbose or rtype not in (0x3E,):
            pr(hexdump(rec, min(dump_limit, 64) if (dump_limit is not None and not verbose)
                       else dump_limit, "      "))
        if extract:
            name = os.path.join(extract, "%scrashlog_rec%02d_%s_prod%03x_rev%d.bin" % (
                tag, idx, tname.replace("(", "_").replace(")", ""), product, revision))
            with open(name, "wb") as fh:
                fh.write(rec)
        cursor += size
        idx += 1
    if idx == 0:
        pr("    (no CrashLog record found in this payload)")
    rest = data[cursor:]
    nz = sum(1 for b in rest if b)
    if idx and nz and u32(data, cursor) not in (0, 0xDEADBEEF):
        pr("    %d undecoded trailing bytes in region (%d non-zero)" % (len(rest), nz))
    return idx


def decode_fw_err(p, pr, dump_limit, verbose, extract, tag):
    if len(p) < 16:
        pr("  (section shorter than the Firmware Error Record Reference header)")
        return
    rtype, rev = p[0], p[1]
    types = ("IPF SAL Error Record", "SOC Firmware Error Record Type1 (Legacy CrashLog Support)",
             "SOC Firmware Error Record Type2")
    pr("  Firmware Error Record Type: %d (%s)" % (rtype, types[rtype] if rtype < 3 else "unknown"))
    pr("  Revision: %d" % rev)
    g = None
    if rev == 0:
        pr("  Record Identifier: 0x%016x" % u64(p, 8))
        offset = 16
    elif rev == 1:
        offset = 8      # what Linux cper.c assumes; Intel's iclg assumes 16 for revision < 2
        pr("  (revision 1: trailing data assumed to start at offset 8, as in Linux cper.c)")
    else:
        g = guid_at(p, 16)
        pr("  Record Identifier GUID: %s%s" % (
            g, "  = Intel CrashLog" if g == GUID_CRASHLOG else ""))
        offset = 32
    body = p[offset:]
    pr("  trailing record data: %d bytes" % len(body))
    if g == GUID_CRASHLOG or (g is None and rtype in (1, 2)):
        pr("  Intel CrashLog region:")
        walk_crashlog_region(body, pr, dump_limit, verbose, extract, tag)
        pr("  (Full decode: Intel 'iclg' from https://github.com/intel/crashlog - "
           "'iclg info|triage|decode FILE' where FILE = 'BERR' + raw region, or BERT table + region.)")


# --------------------------------------------------------------------------
# Generic Error Status Block walk
# --------------------------------------------------------------------------
def parse_bert_table(data, pr):
    length = u32(data, 4)
    pr("ACPI BERT table header:")
    pr("  signature=%s length=%d revision=%d checksum=0x%02x (%s)" % (
        cstr(data[0:4]), length, data[8], data[9],
        "sum OK" if length <= len(data) and sum(data[:length]) & 0xFF == 0 else "sum BAD/unknown"))
    pr("  oem_id='%s' oem_table_id='%s' oem_revision=0x%x creator_id='%s' creator_revision=0x%x" % (
        cstr(data[10:16]), cstr(data[16:24]), u32(data, 24), cstr(data[28:32]), u32(data, 32)))
    pr("  boot_error_region_length=%d (0x%x)  boot_error_region_address=0x%016x" % (
        u32(data, 36), u32(data, 36), u64(data, 40)))
    return length


def walk_region(region, pr, dump_limit, verbose, extract):
    pr("boot error region: %d bytes" % len(region))
    off = 0
    nblk = 0
    while off + 20 <= len(region):
        bs, rdo, rdl, dl, sev = struct.unpack_from("<5I", region, off)
        if not (bs or rdo or rdl or dl or sev):
            pr("[+0x%05x] all-zero status block header: end of records" % off)
            break
        pr("")
        pr("=== Generic Error Status Block %d at offset 0x%x ===" % (nblk, off))
        cleared = ""
        if bs == 0:
            cleared = ("  <-- 0: cleared by Linux bert.c after boot-time processing "
                       "(or never set); walking by data_length")
        pr("  block_status    : 0x%08x  UC_valid=%d CE_valid=%d multi_UC=%d multi_CE=%d "
           "entry_count=%d%s" % (bs, bit(bs, 0), bit(bs, 1), bit(bs, 2), bit(bs, 3),
                                 bits(bs, 11, 4), cleared))
        pr("  raw_data_offset : %d" % rdo)
        pr("  raw_data_length : %d" % rdl)
        pr("  data_length     : %d" % dl)
        pr("  error_severity  : %d (%s)" % (sev, SEVERITY.get(sev, "reserved")))
        est_len = (rdo + rdl) if rdl else (20 + dl)
        pr("  status block length (as Linux cper_estatus_len): %d%s" % (
            est_len, "  -> >= 1024, which is why the kernel printed 'Skipped' instead of the record"
            if est_len >= 1024 else ""))
        if dl > len(region) - off - 20:
            pr("  ERROR: data_length exceeds the region (%d bytes left); not a valid status block. "
               "First bytes:" % (len(region) - off - 20))
            pr(hexdump(region[off:off + 64], 64, "    ", off))
            break
        if dl and dl < 64:
            pr("  ERROR: data_length smaller than one generic error data entry")
        p = off + 20
        end = off + 20 + dl
        nent = 0
        while p < end:
            if end - p < 64:
                pr("  ERROR: %d stray bytes at the end of the data area" % (end - p))
                break
            g = guid_at(region, p)
            esev, rev, vbits, flags, edl = struct.unpack_from("<IHBBI", region, p + 16)
            hdr = 72 if (rev >> 8) >= 3 else 64
            pr("")
            pr("  --- Generic Error Data Entry %d at offset 0x%x ---" % (nent, p))
            pr("  section_type      : %s  (%s)" % (g, SECTION_GUIDS.get(g, "unknown section type")))
            pr("  error_severity    : %d (%s)" % (esev, SEVERITY.get(esev, "reserved")))
            pr("  revision          : 0x%04x (entry header %d bytes)" % (rev, hdr))
            pr("  validation_bits   : 0x%02x (FRU_ID=%d FRU_TEXT=%d TIMESTAMP=%d)" % (
                vbits, bit(vbits, 0), bit(vbits, 1), bit(vbits, 2)))
            fl = [n for b, n in ENTRY_FLAGS if bit(flags, b)]
            pr("  flags             : 0x%02x (%s)" % (flags, " ".join(fl) or "-"))
            pr("  error_data_length : %d" % edl)
            pr("  fru_id            : %s%s" % (guid_at(region, p + 28),
                                             "" if bit(vbits, 0) else "  (not marked valid)"))
            pr("  fru_text          : '%s'%s" % (cstr(region[p + 44:p + 64]),
                                                "" if bit(vbits, 1) else "  (not marked valid)"))
            if hdr == 72:
                pr("  timestamp         : %s%s" % (fmt_timestamp(region[p + 64:p + 72]),
                                                  "" if bit(vbits, 2) else "  (not marked valid)"))
            if hdr + edl > end - p:
                pr("  ERROR: entry (%d + %d bytes) overruns the data area (%d bytes left); "
                   "decoding what is there" % (hdr, edl, end - p))
            payload = region[p + hdr:min(p + hdr + edl, end)]
            pr("  payload (first %s bytes of %d):" % (
                "all" if dump_limit is None else str(min(dump_limit, len(payload))), len(payload)))
            pr(hexdump(payload, dump_limit, "    "))
            tag = "blk%d_ent%d_" % (nblk, nent)
            if extract:
                with open(os.path.join(extract, tag + "payload.bin"), "wb") as fh:
                    fh.write(payload)
            try:
                if g == GUID_PROC_IA:
                    decode_proc_ia(payload, pr, dump_limit)
                elif g == GUID_PROC_GENERIC:
                    decode_proc_generic(payload, pr)
                elif g == GUID_FW_ERR:
                    decode_fw_err(payload, pr, dump_limit, verbose, extract, tag)
                elif g == GUID_MEM:
                    decode_mem(payload, pr)
            except (struct.error, IndexError, ValueError) as exc:
                pr("  (decode of this section aborted: %s: %s)" % (type(exc).__name__, exc))
            nent += 1
            p += hdr + edl
        if bs and bits(bs, 11, 4) != nent:
            pr("  NOTE: block_status entry_count=%d but %d entries were walked" % (
                bits(bs, 11, 4), nent))
        pr("")
        pr("  entries in this block: %d" % nent)
        if rdl:
            raw = region[off + rdo:off + rdo + rdl]
            pr("  raw data (%d bytes at block offset %d):" % (len(raw), rdo))
            pr(hexdump(raw, dump_limit, "    "))
        nblk += 1
        if est_len < 20:
            pr("  ERROR: status block length < 20; stopping")
            break
        off += est_len
    rest = region[off:]
    nz = sum(1 for b in rest if b)
    pr("")
    pr("status blocks found: %d; bytes after the last block: %d (%d non-zero)" % (
        nblk, len(rest), nz))
    if nblk == 0 and any(region):
        pr("No status block could be parsed although the region is not empty; first 256 bytes:")
        pr(hexdump(region, 256, "  "))
    return nblk


def main(argv=None):
    ap = argparse.ArgumentParser(description="Parse an ACPI BERT boot error region dump.")
    ap.add_argument("file")
    ap.add_argument("--dump", type=int, default=256, metavar="N",
                    help="hexdump at most N bytes of each payload (default 256)")
    ap.add_argument("--full", action="store_true", help="hexdump payloads completely")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list every MCA bank of CrashLog MCA records and dump records fully")
    ap.add_argument("--extract", metavar="DIR",
                    help="write region ('BERR'-prefixed, iclg-readable), section payloads and "
                         "CrashLog records into DIR")
    args = ap.parse_args(argv)
    dump_limit = None if args.full else max(0, args.dump)

    with open(args.file, "rb") as fh:
        data = fh.read()

    def pr(line=""):
        sys.stdout.write(line + "\n")

    pr("file: %s  size: %d bytes" % (args.file, len(data)))
    if not data:
        pr("EMPTY FILE (the copy failed, or the file was read without root).")
        return 1
    region = data
    if data[:4] == b"BERT" and len(data) >= 48 and 48 <= u32(data, 4) <= len(data):
        tlen = parse_bert_table(data, pr)
        region = data[tlen:]
        if not region:
            pr("This file is only the ACPI table; the error records are in "
               "/sys/firmware/acpi/tables/data/BERT.")
            return 0
    elif data[:4] == b"BERR":
        pr("'BERR' prefix found (iclg file format); skipping 4 bytes")
        region = data[4:]
    if args.extract:
        os.makedirs(args.extract, exist_ok=True)
        with open(os.path.join(args.extract, "region.berr"), "wb") as fh:
            fh.write(b"BERR" + region)
    walk_region(region, pr, dump_limit, args.verbose, args.extract)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
