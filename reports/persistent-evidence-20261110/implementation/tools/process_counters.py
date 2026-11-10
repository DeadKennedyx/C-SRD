"""Linux process CPU clocks and sampled RSS, with explicit identity continuity.

The collector is outside the processes it measures. CPU clocks include all
threads of a process, not its children. A phase includes acknowledged IPC
boundaries; no-work controls quantify that cost. This is not a security sandbox.
"""
import ctypes
import os
from pathlib import Path
import threading
import time


class Timespec(ctypes.Structure):
    _fields_ = [("seconds", ctypes.c_long), ("nanoseconds", ctypes.c_long)]


def cpu_clock(pid):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.clock_getcpuclockid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    libc.clock_gettime.argtypes = [ctypes.c_int, ctypes.POINTER(Timespec)]
    libc.clock_getres.argtypes = [ctypes.c_int, ctypes.POINTER(Timespec)]
    clock = ctypes.c_int()
    status = libc.clock_getcpuclockid(pid, ctypes.byref(clock))
    if status:
        raise OSError(status, os.strerror(status))
    value, resolution = Timespec(), Timespec()
    if libc.clock_gettime(clock, ctypes.byref(value)) or libc.clock_getres(clock, ctypes.byref(resolution)):
        error = ctypes.get_errno(); raise OSError(error, os.strerror(error))
    return value.seconds*10**9+value.nanoseconds, resolution.seconds*10**9+resolution.nanoseconds


def process(pid):
    path = Path("/proc") / str(pid)
    raw = (path / "stat").read_text()
    fields = raw[raw.rfind(")")+2:].split()
    return {"pid": pid, "parent": int(fields[1]), "start_ticks": int(fields[19]),
            "rss_bytes": max(0, int(fields[21]))*os.sysconf("SC_PAGE_SIZE"),
            "executable": str((path / "exe").resolve(strict=True))}


def family(root, role):
    rows = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            row = process(int(path.name)); rows[row["pid"]] = row
        except (OSError, ValueError, IndexError):
            continue
    selected = {root}
    while True:
        expanded = selected | {p for p, r in rows.items() if r["parent"] in selected}
        if selected == expanded: break
        selected = expanded
    if root not in rows:
        raise ValueError("measured root process disappeared")
    result = {}
    for pid in sorted(selected):
        row = rows[pid]
        row["role"] = role if pid == root else ("native" if Path(row["executable"]).name == "decompile" else "other")
        row["cpu_ns"], row["clock_resolution_ns"] = cpu_clock(pid)
        # Check identity again after clock lookup to detect PID reuse/races.
        if process(pid)["start_ticks"] != row["start_ticks"]:
            raise ValueError("process identity changed while reading counters")
        result[f"{pid}:{row['start_ticks']}"] = row
    return result


def difference(before, after, stable=True):
    if stable and set(before) != set(after):
        raise ValueError("measured process family changed during phase")
    if set(before)-set(after):
        raise ValueError("lost process CPU counter")
    totals = {}
    for key, row in after.items():
        previous = before.get(key)
        if previous and (previous["role"], previous["executable"]) != (row["role"], row["executable"]):
            raise ValueError("measured process changed executable or role")
        delta = row["cpu_ns"]-(previous["cpu_ns"] if previous else 0)
        if delta < 0:
            raise ValueError("nonmonotonic process CPU clock")
        totals[row["role"]] = totals.get(row["role"], 0)+delta
    return totals


class Phase:
    def __init__(self, root, role, stable=True, interval=0.005):
        if not 0 < interval <= 1:
            raise ValueError("positive bounded sample interval required")
        self.root, self.role, self.stable, self.interval = root, role, stable, interval
        self.before = family(root, role)
        self.samples, self.errors = [], []
        self.stop = threading.Event()
        self.start = time.perf_counter_ns()
        self.thread = threading.Thread(target=self.sample, daemon=True)
        self.thread.start()

    def sample(self):
        while not self.stop.is_set():
            values = {}
            for key, old in self.before.items():
                try:
                    row = process(old["pid"])
                    if row["start_ticks"] != old["start_ticks"]:
                        raise ValueError("PID reused")
                    values[old["role"]] = values.get(old["role"], 0)+row["rss_bytes"]
                except (OSError, ValueError, IndexError) as error:
                    self.errors.append(str(error))
            self.samples.append({"elapsed_ns": time.perf_counter_ns()-self.start, "rss_bytes": values})
            self.stop.wait(self.interval)

    def finish(self):
        result = {"status": "completed", "before": self.before, "sample_interval_seconds": self.interval,
                  "cpu_scope": "POSIX process clocks; all process threads; observer collector excluded",
                  "memory_scope": "sampled RSS plus endpoints; shared pages counted per process; peaks can be missed; retained memory is not allocation cost"}
        try:
            after = family(self.root, self.role)
            result["after"] = after
            result["cpu_ns"] = difference(self.before, after, self.stable)
        except (OSError, ValueError, IndexError) as error:
            result.update(status="invalid-counters", error=str(error), cpu_ns=None)
        finally:
            result["wall_ns"] = time.perf_counter_ns()-self.start
            self.stop.set(); self.thread.join()
        result.update(samples=self.samples, sample_errors=self.errors)
        if self.stable and self.errors:
            result.update(status="invalid-counters", cpu_ns=None)
        for name in ("before", "after"):
            values = {}
            for row in result.get(name, {}).values():
                values[row["role"]] = values.get(row["role"], 0)+row["rss_bytes"]
            result[name+"_rss_bytes"] = values
        samples = [s["rss_bytes"] for s in self.samples]+[result["before_rss_bytes"], result["after_rss_bytes"]]
        roles = set().union(*(s.keys() for s in samples))
        result["peak_sampled_rss_bytes"] = {role: max(s.get(role, 0) for s in samples) for role in roles}
        result["peak_sampled_sum_rss_bytes"] = max(sum(s.values()) for s in samples)
        return result
