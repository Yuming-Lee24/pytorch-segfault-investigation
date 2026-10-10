#!/usr/bin/env python
"""Reproduce the CPU 0 crash on demand.

Runs a short child process pinned to one CPU, over and over, until one of
them dies, then reports how it died. CPU only: no GPU, no root.

    python scripts/reproduce_crash.py                  # CPU 0: crashes within a second
    python scripts/reproduce_crash.py --busy 2,3       # CPU 0 held to 54x: expected to pass
    python scripts/reproduce_crash.py --cpu 1          # another core: expected to pass

WARNING: on CPU 0 this can also reset the whole machine. After a reset, run
`sudo scripts/collect_root_diag.sh` before anything else.

Two workloads are available with --method:
    keyerror  a tight loop over the interpreter path most crashes were on
              (a KeyError raised and caught inside inspect.getattr_static)
    import    `import torch, torchvision`, the command that first segfaulted
"""
import argparse
import os
import signal
import subprocess
import sys
import time

IMPORT = "import torch, torchvision"
KEYERROR = """
import inspect, time
class Base: pass
class Leaf(Base): pass
obj, missing = Leaf(), object()
end = time.monotonic() + {seconds}
while time.monotonic() < end:
    for _ in range(2000):
        if inspect.getattr_static(obj, "no_such_attribute", missing) is not missing:
            raise SystemExit("getattr_static returned a wrong result")
"""


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def mhz(cpu):
    v = read("/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq" % cpu)
    return int(v) // 1000 if v.isdigit() else 0


def describe(rc):
    if rc < 0:
        try:
            return "killed by " + signal.Signals(-rc).name
        except ValueError:
            return "killed by signal %d" % -rc
    return "exit status %d" % rc


def kernel_lines(pid, since):
    try:
        out = subprocess.run(
            ["journalctl", "-k", "--no-pager", "-o", "short-iso", "--since", "@%d" % int(since)],
            capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    lines = out.splitlines()
    hits = [i for i, line in enumerate(lines) if "[%d]" % pid in line]
    # The "Code:" line follows the fault line it belongs to.
    return [lines[j] for i in hits for j in (i, i + 1)
            if j < len(lines) and (j == i or "Code:" in lines[j])]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cpu", type=int, default=0, help="CPU to pin the workload to (default 0)")
    ap.add_argument("--method", choices=["keyerror", "import"], default="keyerror")
    ap.add_argument("--max", type=int, default=300, help="give up after this many runs")
    ap.add_argument("--seconds", type=float, default=1.0,
                    help="length of each keyerror run (default 1)")
    ap.add_argument("--busy", default="",
                    help="CPUs to keep busy meanwhile, e.g. 2,3 (two busy P-cores lower "
                         "the turbo limit from 57x to 54x)")
    ap.add_argument("--keep-going", action="store_true",
                    help="count crashes over all runs instead of stopping at the first")
    ap.add_argument("--min-mhz", type=int, default=5600,
                    help="warn if the CPU averaged below this; the fault needs top speed")
    args = ap.parse_args()

    code = IMPORT if args.method == "import" else KEYERROR.format(seconds=args.seconds)
    env = dict(os.environ, PYTHONHASHSEED="0")
    env.pop("PYTHONFAULTHANDLER", None)   # let the kernel log the fault address and CPU

    busy = [c for c in args.busy.split(",") if c]
    spinners = [subprocess.Popen(["taskset", "-c", c, sys.executable, "-c", "while True: pass"])
                for c in busy]
    if spinners:
        time.sleep(2)
    try:
        return run(args, code, env, busy)
    finally:
        for p in spinners:
            p.kill()


def run(args, code, env, busy):
    print("CPU %d, method %s, up to %d runs%s"
          % (args.cpu, args.method, args.max,
             ", CPUs %s kept busy" % ",".join(busy) if busy else ""), flush=True)
    speeds, t0, failures = [], time.time(), 0
    for n in range(1, args.max + 1):
        started = time.time()
        p = subprocess.Popen(["taskset", "-c", str(args.cpu), sys.executable, "-c", code],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        last = 0
        while p.poll() is None:
            last = mhz(args.cpu) or last
            time.sleep(0.1)
        out, err = p.communicate()
        if p.returncode == 0:
            speeds.append(last)             # speed near the end of a full-length run
        if p.returncode != 0:
            failures += 1
            print("\nCRASH on run %d, %.2f s into it: %s"
                  % (n, time.time() - started, describe(p.returncode)))
            for line in err.strip().splitlines()[-6:]:
                print("  stderr: " + line[:200])
            time.sleep(1)                   # give the kernel log a moment
            for line in kernel_lines(p.pid, started):
                print("  kernel: " + line.split("kernel: ", 1)[-1][:230])
            sys.stdout.flush()
            if not args.keep_going:
                return 1
        if n % 10 == 0:
            print("  %d runs clean, %d MHz" % (n, sum(speeds[-10:]) // 10),
                  flush=True)

    # Runs that crash at once end before the frequency reading settles, so the
    # average only means something for runs that lasted.
    avg = sum(speeds) // max(len(speeds), 1)
    print("\n%s in %d runs (%.0f s), CPU %d at about %d MHz"
          % ("%d crashes" % failures if failures else "No crash",
             args.max, time.time() - t0, args.cpu, avg))
    if not failures and avg < args.min_mhz:
        print("That is below %d MHz, so this pass proves nothing. Close other programs "
              "and run it again." % args.min_mhz)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
