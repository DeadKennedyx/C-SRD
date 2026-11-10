"""Measure a trusted command and descendants in a dedicated Unix collector.

No third-party packages. Linux adds orphan reaping and sampled process-tree RSS.
This is a benchmark collector, not a security sandbox or a hard resource limiter.
"""
import ctypes
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def environment():
    return {"system": platform.platform(), "machine": platform.machine(),
            "python": sys.version, "logical_cpus": os.cpu_count(),
            "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "load_average": list(os.getloadavg()),
            "clock": vars(time.get_clock_info("perf_counter"))}


def proc_sample(session):
    """RSS at approximately one instant; CPU includes already-waited children."""
    processes, missed = [], 0
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            raw = (path / "stat").read_text()
            # comm may contain spaces and ')'; fields after its final ')' are numeric/state.
            fields = raw[raw.rfind(")") + 2:].split()
            processes.append({"pid": int(path.name), "parent": int(fields[1]), "session": int(fields[3]),
                              "start": int(fields[19]),
                              "rss": max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE"),
                              "cpu": sum(int(fields[i]) for i in (11, 12, 13, 14)) /
                                     os.sysconf("SC_CLK_TCK")})
        except (OSError, ValueError, IndexError):
            missed += 1
    owned = {p["pid"] for p in processes if p["session"] == session or p["parent"] == os.getpid()}
    while True:
        expanded = owned | {p["pid"] for p in processes if p["parent"] in owned}
        if expanded == owned:
            break
        owned = expanded
    return [p for p in processes if p["pid"] in owned], missed


def collect(config, directory):
    linux = sys.platform.startswith("linux")
    subreaper = linux and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    if (config.get("cpu_seconds") or config.get("memory_bytes")) and not linux:
        raise ValueError("CPU and aggregate-RSS budgets require Linux /proc sampling")
    if linux and not subreaper:
        raise RuntimeError("Linux child-subreaper setup failed; descendant CPU accounting is unavailable")
    interval = config.get("sample_seconds", 0.01)
    if interval <= 0 or config["wall_seconds"] <= 0:
        raise ValueError("positive sampling interval and wall budget required")
    result = {"schema_version": 1, "argv": config["argv"], "status": "running",
              "budgets": {k: config.get(k) for k in ("wall_seconds", "cpu_seconds", "memory_bytes")},
              "sample_seconds": interval, "subreaper": subreaper, "samples": [],
              "memory_scope": "sampled sum of live session RSS; shared pages counted per process; may miss peaks",
              "cpu_scope": "wait4 user+system, including waited descendants; Linux also reaps orphan descendants",
              "descendant_accounting": "reaped-tree" if subreaper else "waited-descendants-only",
              "budget_enforcement": "sampled soft limit; overshoot and cleanup time are recorded"}
    start = time.perf_counter()
    usages, seen, missed, root_status, exhausted = [], set(), 0, None, None
    with (directory / "stdout.txt").open("wb") as stdout, (directory / "stderr.txt").open("wb") as stderr:
        try:
            process = subprocess.Popen(config["argv"], stdin=subprocess.DEVNULL, stdout=stdout,
                                       stderr=stderr, start_new_session=True, cwd=config.get("cwd"))
        except OSError as error:
            result.update(status="launch-error", error=str(error), wall_seconds=time.perf_counter() - start)
            save(directory / "resources.json", result)
            return result
        no_children = False
        while True:
            while True:
                try:
                    pid, status, usage = os.wait4(-1, os.WNOHANG)
                except ChildProcessError:
                    no_children = True
                    break
                if pid == 0:
                    break
                usages.append(usage)
                if pid == process.pid:
                    root_status = os.waitstatus_to_exitcode(status)
                    process.returncode = root_status  # wait4, not Popen, owns reaping.
            now = time.perf_counter() - start
            if linux:
                members, failures = proc_sample(process.pid)
                missed += failures
                seen.update((p["pid"], p["start"]) for p in members)
                rss = sum(p["rss"] for p in members)
                cpu = sum(p["cpu"] for p in members) + sum(u.ru_utime + u.ru_stime for u in usages)
                result["samples"].append({"seconds": now, "rss_bytes": rss,
                                          "cpu_seconds": cpu, "live_processes": len(members)})
            else:
                members, rss, cpu = [], None, None
            if no_children:
                break
            if exhausted is None:
                if now >= config["wall_seconds"]:
                    exhausted = "wall-budget"
                elif config.get("cpu_seconds") and cpu >= config["cpu_seconds"]:
                    exhausted = "cpu-budget"
                elif config.get("memory_bytes") and rss >= config["memory_bytes"]:
                    exhausted = "memory-budget"
                if exhausted:
                    result["budget_trigger_seconds"] = now
            if exhausted:
                # Group covers the launcher and usual children. Session scan also covers
                # tools such as GDB that give their inferior a separate process group.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                for member in members:
                    try:
                        os.kill(member["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            time.sleep(interval)
    wall = time.perf_counter() - start
    user, system = sum(u.ru_utime for u in usages), sum(u.ru_stime for u in usages)
    # Completion between polls cannot count as success outside its declared budget.
    if exhausted is None and wall > config["wall_seconds"]:
        exhausted = "wall-budget"
    if exhausted is None and config.get("cpu_seconds") and user + system > config["cpu_seconds"]:
        exhausted = "cpu-budget"
    result.update(status=exhausted or ("completed" if root_status == 0 else "nonzero-exit"),
                  returncode=root_status, wall_seconds=wall, cpu_user_seconds=user,
                  cpu_system_seconds=system, cpu_seconds=user + system,
                  mean_cpu_cores=(user + system) / wall,
                  peak_process_rss_bytes=max((u.ru_maxrss for u in usages), default=0) *
                                         (1 if sys.platform == "darwin" else 1024),
                  peak_sampled_tree_rss_bytes=max((s["rss_bytes"] for s in result["samples"]), default=None),
                  sampled_processes=len(seen) if linux else None, sample_read_failures=missed,
                  reaped_children=len(usages),
                  minor_page_faults=sum(u.ru_minflt for u in usages),
                  major_page_faults=sum(u.ru_majflt for u in usages),
                  voluntary_context_switches=sum(u.ru_nvcsw for u in usages),
                  involuntary_context_switches=sum(u.ru_nivcsw for u in usages),
                  block_inputs=sum(u.ru_inblock for u in usages),
                  block_outputs=sum(u.ru_oublock for u in usages),
                  stdout_bytes=(directory / "stdout.txt").stat().st_size,
                  stderr_bytes=(directory / "stderr.txt").stat().st_size)
    save(directory / "resources.json", result)
    return result


def measure(argv, directory, wall_seconds=120, cpu_seconds=None, memory_bytes=None,
            sample_seconds=0.01):
    """Run collection in a separate process so subreaping cannot affect the caller."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    config = {"argv": list(map(str, argv)), "wall_seconds": wall_seconds,
              "cpu_seconds": cpu_seconds, "memory_bytes": memory_bytes, "sample_seconds": sample_seconds}
    save(directory / "command.json", config)
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(directory)],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("resource collector failed: " + result.stderr[-4000:])
    return json.loads((directory / "resources.json").read_text())


if __name__ == "__main__":
    destination = Path(sys.argv[1])
    collect(json.loads((destination / "command.json").read_text()), destination)
