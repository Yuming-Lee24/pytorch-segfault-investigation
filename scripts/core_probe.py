#!/usr/bin/env python
"""Per-core CPU self-check: find out whether faults follow a specific CPU.

Pins deterministic, self-verifying work to one CPU at a time and records
wrong results, crashes and kernel fault messages per CPU. CPU only: it
never touches the GPU, and it needs no root.

    # one CPU busy at a time, the rest idle (light load, maximum turbo)
    python scripts/core_probe.py sweep --mode burst --seconds 20 --rounds 3
    python scripts/core_probe.py sweep --mode steady --seconds 20
    # sleep, then kernel-heavy work straight after each wake-up
    python scripts/core_probe.py sweep --mode wake --seconds 20
    # every CPU busy at once (heavy load, the regime stress tests cover)
    python scripts/core_probe.py sweep --mode steady --seconds 60 --parallel
    # short-lived processes, like the `import torch` that segfaulted
    python scripts/core_probe.py sweep --mode spawn --count 20 --cpus 0-7
    # the same, with every other CPU kept busy
    python scripts/core_probe.py sweep --mode spawn --count 40 --cpus 0 --load-others
    # the same, with two other P-cores busy: caps turbo at 5.4 GHz, rest stay idle
    python scripts/core_probe.py sweep --mode spawn --count 40 --cpus 0 --load-cpus 2,3

Results are appended to logs/core_probe/<timestamp>_<mode>.tsv, one row per
CPU per round, and flushed to disk after every row.
"""
import argparse
import collections
import faulthandler
import glob
import hashlib
import heapq
import json
import math
import mmap
import os
import random
import re
import resource
import signal
import struct
import subprocess
import sys
import time
import zlib
from datetime import datetime

KERNEL_FAULT = re.compile(
    r"segfault|general protection|traps:|BUG:|Oops|UBSAN|Hardware Error|mce:|"
    r"soft lockup|rcu.*stall",
    re.IGNORECASE,
)
KERNEL_FATAL = re.compile(r"BUG:|Oops")
SPAWN_CODE = "import torch, torchvision"


# --------------------------------------------------------------- work units

class Corrupt(Exception):
    """A unit verified its own output and found it wrong."""


def _diff(expected, got, limit=8):
    """Describe where two byte strings differ: offsets and XOR of the bytes."""
    if len(expected) != len(got):
        return {"len_expected": len(expected), "len_got": len(got)}
    out = []
    step = 1 << 16
    for base in range(0, len(expected), step):
        a, b = expected[base:base + step], got[base:base + step]
        if a == b:
            continue
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                out.append({"offset": base + i, "xor": x ^ y})
                if len(out) >= limit:
                    return {"first_diffs": out, "truncated": True}
    return {"first_diffs": out}


def build_units():
    """Return [(name, callable)] where each callable returns a digest."""
    rand = hashlib.shake_256(b"core-probe-rand").digest(512 * 1024)
    big = hashlib.shake_256(b"core-probe-big").digest(16 * 1024 * 1024)

    vocab = [b"alpha", b"beta", b"gamma", b"delta", b"epsilon", b"zeta",
             b"eta", b"theta", b"iota", b"kappa", b"lambda", b"mu"]
    state, words = 12345, []
    for _ in range(40000):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        words.append(vocab[state % len(vocab)] + b"%d" % (state % 97))
    text = b" ".join(words)

    state, ints = 987654321, []
    for _ in range(50000):
        state = (state * 6364136223846793005 + 1442695040888963407) & (2 ** 64 - 1)
        ints.append(state >> 11)

    record = {"k%d" % i: [i, i * 0.5, str(i * 7919), {"n": i % 13}] for i in range(1500)}
    word_re = re.compile(rb"\b(?:alpha|theta)(\d+)\b")

    def pyobj():
        d, lst, acc = {}, [], 1
        for i in range(3000):
            k = "k%d" % (i * 7919 % 613)
            d[k] = d.get(k, 0) + i * i
            lst.append((i ^ (i >> 3), k))
            acc = (acc * 6364136223846793005 + 1442695040888963407 + i) % (1 << 521)
        lst.sort()
        s = ",".join("%s=%d" % kv for kv in d.items())
        t = repr(lst[::37]) + hex(acc)
        try:
            {}["missing"]
        except KeyError:
            t += "E"
        return hashlib.sha256((s + t).encode()).digest()

    def compress():
        packed = zlib.compress(text, 6)
        back = zlib.decompress(packed)
        if back != text:
            raise Corrupt(json.dumps(_diff(text, back)))
        return hashlib.sha1(packed).digest()

    def hashes():
        h = hashlib.sha256()
        for algo in ("md5", "sha256", "sha512", "blake2b", "sha3_256"):
            h.update(hashlib.new(algo, rand).digest())
        return h.digest()

    def sorting():
        s = sorted(ints)
        small = heapq.nsmallest(500, ints)
        if small != s[:500]:
            raise Corrupt("heapq.nsmallest disagrees with sorted")
        return hashlib.sha256(struct.pack("<2000Q", *s[::25])).digest()

    def floats():
        total = math.fsum(math.sin(i * 0.001) * math.sqrt(i) / (1.0 + math.exp(-i * 1e-4))
                          for i in range(20000))
        return repr(total).encode()

    def textproc():
        dumped = json.dumps(record, sort_keys=True)
        if json.loads(dumped) != record:
            raise Corrupt("json round trip changed the data")
        found = word_re.findall(text)
        return hashlib.sha256(dumped.encode() + b"".join(found)).digest()

    def memory():
        a = bytearray(big)
        b = bytes(a)
        if b != big:
            raise Corrupt(json.dumps(_diff(big, b)))
        return zlib.crc32(a).to_bytes(4, "big")

    units = [("pyobj", pyobj), ("compress", compress), ("hashes", hashes),
             ("sorting", sorting), ("floats", floats), ("textproc", textproc),
             ("memory", memory)]

    try:
        import numpy as np
    except ImportError:
        return units

    u64 = np.frombuffer(rand[:250000 * 8], dtype=np.uint64).copy()
    f64 = (u64 >> np.uint64(11)).astype(np.float64) / float(1 << 53)
    mat = f64[:200 * 200].reshape(200, 200).copy()

    def np_int():
        x = u64.copy()
        for _ in range(4):
            x ^= x << np.uint64(13)
            x ^= x >> np.uint64(7)
            x ^= x << np.uint64(17)
        return hashlib.sha256(x.tobytes()).digest()

    def np_float():
        y = np.sqrt(f64 * f64 + 1.0) / (f64 + 3.0)
        return hashlib.sha256(y.tobytes()).digest()

    def np_blas():
        return hashlib.sha256((mat @ mat.T).tobytes()).digest()

    return units + [("np_int", np_int), ("np_float", np_float), ("np_blas", np_blas)]


def call(fn):
    try:
        return fn().hex()
    except Corrupt as e:
        return "CORRUPT:%s" % e


# ------------------------------------------------------------------- worker

def wake_loop(args):
    """Sleep into deep idle, then do kernel-heavy work the moment the CPU wakes.

    Each pass maps, touches and unmaps anonymous memory (page faults, then the
    page-freeing path the 2026-10-07 kernel oops died in), moves data through
    a pipe, and forks a child that exits straight away.
    """
    rng = random.Random(args.seed)
    payload = hashlib.shake_256(b"core-probe-pipe").digest(4096)
    child_code = zlib.crc32(payload) & 0x3F
    t0 = time.monotonic()
    iterations, mismatches = 0, []

    def bad(what, **extra):
        event = dict(unit=what, iteration=iterations,
                     elapsed=round(time.monotonic() - t0, 3), **extra)
        mismatches.append(event)
        print("MISMATCH " + json.dumps(event), file=sys.stderr, flush=True)

    while time.monotonic() - t0 < args.seconds:
        time.sleep(rng.uniform(0.0002, 0.008))

        size = rng.choice((1, 2, 4, 8)) << 20
        fill = bytes([rng.randrange(1, 256)]) * (size // 4096)
        m = mmap.mmap(-1, size)
        m[::4096] = fill
        if m[::4096] != fill:
            bad("mmap readback", size=size)
        m.close()

        r, w = os.pipe()
        os.write(w, payload)
        if os.read(r, len(payload)) != payload:
            bad("pipe")
        os.close(r)
        os.close(w)

        pid = os.fork()
        if pid == 0:
            os._exit(child_code)
        status = os.waitpid(pid, 0)[1]
        if os.WIFSIGNALED(status) or os.WEXITSTATUS(status) != child_code:
            bad("child exit", status=status)
        iterations += 1

    print(json.dumps({"cpu": args.cpu, "iterations": iterations,
                      "mismatches": mismatches, "startup_disagreements": [],
                      "reference": {}}), flush=True)


def worker(args):
    os.sched_setaffinity(0, {args.cpu})
    faulthandler.enable()
    if args.mode == "wake":
        return wake_loop(args)
    units = build_units()

    # Reference digests: three runs on this CPU must agree with each other.
    reference, startup_disagreements = {}, []
    for name, fn in units:
        got = [call(fn) for _ in range(3)]
        reference[name] = collections.Counter(got).most_common(1)[0][0]
        if len(set(got)) != 1:
            startup_disagreements.append({"unit": name, "got": got})

    rng = random.Random(args.seed)
    t0 = time.monotonic()
    iterations, mismatches = 0, []
    while time.monotonic() - t0 < args.seconds:
        for name, fn in units:
            if args.mode == "burst":
                time.sleep(rng.uniform(0.0005, 0.03))
            got = call(fn)
            if got != reference[name]:
                event = {"unit": name, "iteration": iterations,
                         "elapsed": round(time.monotonic() - t0, 3),
                         "expected": reference[name], "got": got}
                mismatches.append(event)
                print("MISMATCH " + json.dumps(event), file=sys.stderr, flush=True)
        iterations += 1

    print(json.dumps({"cpu": args.cpu, "iterations": iterations,
                      "mismatches": mismatches,
                      "startup_disagreements": startup_disagreements,
                      "reference": reference}), flush=True)


# -------------------------------------------------------------------- sweep

def parse_cpus(spec):
    cpus = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        cpus.extend(range(int(lo), int(hi or lo) + 1))
    return cpus


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def core_types():
    p = set(parse_cpus(read("/sys/devices/cpu_core/cpus", "0")))
    return lambda cpu: "P" if cpu in p else "E"


def kernel_events(since_epoch):
    try:
        out = subprocess.run(
            ["journalctl", "-k", "--no-pager", "-o", "short-iso",
             "--since", "@%d" % int(since_epoch)],
            capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in out.splitlines() if KERNEL_FAULT.search(line)]


def core_temp_path(cpu):
    """sysfs file with the temperature of the physical core behind `cpu`."""
    core_id = read("/sys/devices/system/cpu/cpu%d/topology/core_id" % cpu)
    for label in glob.glob("/sys/class/hwmon/hwmon*/temp*_label"):
        if read(os.path.dirname(label) + "/name") == "coretemp" and read(label) == "Core " + core_id:
            return label[:-len("_label")] + "_input"
    return None


class Telemetry:
    """Frequency and core temperature of the CPUs under test, sampled."""

    def __init__(self, cpus):
        self.cpus = cpus
        self.temp_paths = [p for p in map(core_temp_path, cpus) if p]
        self.mhz = []
        self.temp = []

    def sample(self):
        for cpu in self.cpus:
            v = read("/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq" % cpu)
            if v.isdigit():
                self.mhz.append(int(v) // 1000)
        for path in self.temp_paths:
            t = read(path)
            if t.isdigit():
                self.temp.append(int(t) // 1000)

    def summary(self):
        avg = sum(self.mhz) // len(self.mhz) if self.mhz else 0
        return avg, max(self.mhz, default=0), max(self.temp, default=0)


def exit_name(rc):
    if rc is None or rc >= 0:
        return str(rc)
    try:
        return signal.Signals(-rc).name
    except ValueError:
        return "SIG%d" % -rc


def worker_env():
    env = dict(os.environ)
    env.update(PYTHONHASHSEED="0", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", PYTHONFAULTHANDLER="1")
    return env


def run_workers(cpus, args, seed):
    """Run one worker per CPU in `cpus` concurrently; return {cpu: result}."""
    procs = {}
    for cpu in cpus:
        procs[cpu] = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "worker", "--cpu", str(cpu),
             "--seconds", str(args.seconds), "--mode", args.mode, "--seed", str(seed + cpu)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=worker_env())
    tele = {cpu: Telemetry([cpu]) for cpu in cpus}
    while any(p.poll() is None for p in procs.values()):
        for t in tele.values():
            t.sample()
        time.sleep(0.25)

    results = {}
    for cpu, p in procs.items():
        out, err = p.communicate()
        res = {"exit": exit_name(p.returncode), "iterations": 0, "mismatches": 0, "detail": {}}
        try:
            data = json.loads(out.strip().splitlines()[-1])
            res["iterations"] = data["iterations"]
            res["mismatches"] = len(data["mismatches"]) + len(data["startup_disagreements"])
            res["reference"] = data["reference"]
            if res["mismatches"]:
                res["detail"] = {"mismatches": data["mismatches"][:5],
                                 "startup": data["startup_disagreements"][:5]}
        except (IndexError, ValueError, KeyError):
            res["detail"] = {"stderr": err[-1500:]}
        res["telemetry"] = tele[cpu].summary()
        results[cpu] = res
    return results


def run_spawns(cpu, args):
    """Start `count` short-lived interpreters pinned to `cpu`.

    faulthandler is left off on purpose: an unhandled SIGSEGV makes the kernel
    log the fault address and CPU, and with --cores lets apport write a core
    dump to /var/lib/apport/coredump/.
    """
    env = worker_env()
    del env["PYTHONFAULTHANDLER"]
    tele = Telemetry([cpu])
    failures = []
    for i in range(args.count):
        p = subprocess.run(["taskset", "-c", str(cpu), sys.executable, "-c", args.code],
                           capture_output=True, text=True, env=env)
        tele.sample()
        if p.returncode != 0:
            failures.append({"n": i, "pid_time": datetime.now().strftime("%H:%M:%S"),
                             "exit": exit_name(p.returncode), "stderr": p.stderr[:800]})
    exits = sorted({f["exit"] for f in failures})
    return {"exit": ",".join(exits) if exits else "0", "iterations": args.count,
            "mismatches": len(failures), "detail": {"failures": failures[:5]} if failures else {},
            "telemetry": tele.summary()}


def start_load(cpus, idle_priority=False):
    """Spin on `cpus`. At idle priority the spinner only fills otherwise idle time."""
    prefix = ["chrt", "-i", "0"] if idle_priority else []
    return [subprocess.Popen(prefix + ["taskset", "-c", str(c), sys.executable, "-c",
                                       "while True: pass"])
            for c in cpus]


def sweep(args):
    cpus = parse_cpus(args.cpus) if args.cpus else sorted(os.sched_getaffinity(0))
    everything = sorted(os.sched_getaffinity(0))
    kind = core_types()

    # Keep this supervising process off the CPUs it is measuring where possible.
    spare = [c for c in sorted(os.sched_getaffinity(0), reverse=True) if c not in cpus]
    home = spare[0] if spare else None

    if args.cores:
        # apport keeps only the newest few cores in /var/lib/apport/coredump/.
        resource.setrlimit(resource.RLIMIT_CORE, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

    os.makedirs("logs/core_probe", exist_ok=True)
    label = args.mode + ("_parallel" if args.parallel else "")
    if args.load_cpus:
        label += "_load" + args.load_cpus.replace(",", "+")
    elif args.load_others:
        label += "_loaded"
    if args.keep_awake:
        label += "_awake"
    if args.tag:
        label += "_" + args.tag
    path = args.out or "logs/core_probe/%s_%s.tsv" % (
        datetime.now().strftime("%Y%m%d_%H%M%S"), label)
    fresh = not os.path.exists(path)
    log = open(path, "a", buffering=1)

    def emit(*fields):
        line = "\t".join(str(f) for f in fields)
        log.write(line + "\n")
        log.flush()
        os.fsync(log.fileno())
        print(line, flush=True)

    if fresh:
        emit("time", "round", "cpu", "type", "mode", "work", "iterations", "bad", "exit",
             "avg_mhz", "max_mhz", "max_temp_c", "kernel_events", "detail")

    references = collections.defaultdict(dict)   # unit -> {digest: [cpus]}
    slow_rows = 0
    for rnd in range(args.rounds):
        order = list(cpus)
        random.Random(args.seed + rnd).shuffle(order)
        groups = [order] if args.parallel else [[c] for c in order]
        for group in groups:
            if home is not None and not args.parallel:
                os.sched_setaffinity(0, {home if home not in group else spare[-1]})
            if args.load_cpus:
                busy = [c for c in parse_cpus(args.load_cpus) if c not in group]
            elif args.load_others:
                busy = [c for c in everything if c not in group]
            else:
                busy = []
            load = start_load(busy)
            if args.keep_awake:
                load += start_load(group, idle_priority=True)
            if load:
                time.sleep(2)
            started = time.time()
            try:
                if args.mode == "spawn":
                    results = {group[0]: run_spawns(group[0], args)}
                    work = "%d spawns" % args.count
                    if args.code != SPAWN_CODE:
                        work += " (custom code)"
                else:
                    results = run_workers(group, args, args.seed + 1000 * rnd)
                    work = "%ds" % args.seconds
            finally:
                for p in load:
                    p.kill()
                for p in load:
                    p.wait()
            events = kernel_events(started)
            for cpu in group:
                r = results[cpu]
                for unit, digest in r.get("reference", {}).items():
                    references[unit].setdefault(digest, []).append(cpu)
                detail = dict(r["detail"])
                if events:
                    detail["kernel"] = events[:6]
                avg, peak, temp = r["telemetry"]
                if args.require_mhz and avg < args.require_mhz:
                    detail["too_slow"] = "average %d MHz is below --require-mhz" % avg
                    slow_rows += 1
                emit(datetime.now().strftime("%H:%M:%S"), rnd, cpu, kind(cpu), label, work,
                     r["iterations"], r["mismatches"], r["exit"], avg, peak, temp,
                     len(events), json.dumps(detail) if detail else "")
            if any(KERNEL_FATAL.search(e) for e in events):
                emit("STOP", "kernel oops logged; reboot before testing further")
                return 2

    # CPUs of the same type must agree on every reference digest.
    for unit, by_digest in sorted(references.items()):
        if len(by_digest) > 1:
            groups = {d[:12]: sorted(set(c)) for d, c in by_digest.items()}
            emit("NOTE", "reference digests differ between CPUs", unit, json.dumps(groups))
    if slow_rows:
        emit("NOTE", "%d row(s) ran below --require-mhz; a pass there proves nothing" % slow_rows)
    print("Wrote", path)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worker", help="run the self-check on one CPU (used by sweep)")
    w.add_argument("--cpu", type=int, required=True)
    w.add_argument("--seconds", type=float, default=20)
    w.add_argument("--mode", choices=["steady", "burst", "wake"], default="steady")
    w.add_argument("--seed", type=int, default=0)

    s = sub.add_parser("sweep", help="test CPUs in turn and log the results")
    s.add_argument("--cpus", help="for example 0-7 or 0,4,16 (default: all)")
    s.add_argument("--mode", choices=["steady", "burst", "wake", "spawn"], default="burst")
    s.add_argument("--seconds", type=float, default=20, help="per CPU per round")
    s.add_argument("--count", type=int, default=20, help="spawns per CPU per round")
    s.add_argument("--code", default=SPAWN_CODE, help="what each spawned interpreter runs")
    s.add_argument("--rounds", type=int, default=1)
    s.add_argument("--parallel", action="store_true", help="load all CPUs at once")
    s.add_argument("--load-others", action="store_true",
                   help="keep every CPU not under test busy with a spin loop")
    s.add_argument("--load-cpus", help="keep just these CPUs busy, for example 2,3")
    s.add_argument("--keep-awake", action="store_true",
                   help="idle-priority spin loop on the CPU under test, so it never idles")
    s.add_argument("--cores", action="store_true", help="let crashes leave core dumps")
    s.add_argument("--require-mhz", type=int,
                   help="flag rows whose CPU averaged below this frequency")
    s.add_argument("--tag", help="extra text for the mode column")
    s.add_argument("--out", help="append rows to this file instead of a new one")
    s.add_argument("--seed", type=int, default=1)

    args = ap.parse_args()
    if args.cmd == "worker":
        worker(args)
        return 0
    return sweep(args)


if __name__ == "__main__":
    sys.exit(main())
